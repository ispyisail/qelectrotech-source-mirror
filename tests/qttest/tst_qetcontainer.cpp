// SPDX-License-Identifier: GPL-2.0-or-later
#include <QtTest>

#include <QDir>
#include <QFile>

#include "container/qetcontainer.h"

// A project document split into the parts of a .qetz, zipped, unzipped and
// joined back is the document it was: every example, and every .qet in the
// folder QET_CONTAINER_CORPUS names, if set. Whitespace-only text between
// elements is indentation and is not compared; elsewhere it is (a
// title-block value of " ", #973).
class tst_qetcontainer : public QObject
{
	Q_OBJECT

	static QList<QDomNode> children(const QDomNode &node)
	{
		QList<QDomNode> all;
		bool has_element = false;
		for (QDomNode c = node.firstChild() ; !c.isNull() ; c = c.nextSibling()) {
			all << c;
			has_element |= c.isElement();
		}
		if (!has_element) return all;
		QList<QDomNode> kept;
		for (const QDomNode &c : all)
			if (!(c.isText() && c.nodeValue().trimmed().isEmpty())) kept << c;
		return kept;
	}

	// empty when equal, else where they differ
	static QString difference(const QDomNode &a, const QDomNode &b, const QString &path)
	{
		const QString here = path + QLatin1Char('/') + a.nodeName();
		if (a.nodeType() != b.nodeType() || a.nodeName() != b.nodeName())
			return here + QStringLiteral(": %1 vs %2").arg(a.nodeName(), b.nodeName());
		if (!a.isElement() && !a.isDocument() && a.nodeValue() != b.nodeValue())
			return here + QStringLiteral(": value differs");
		if (a.isElement()) {
			const QDomNamedNodeMap aa = a.attributes(), ba = b.attributes();
			if (aa.count() != ba.count())
				return here + QStringLiteral(": %1 vs %2 attributes").arg(aa.count()).arg(ba.count());
			for (int i = 0 ; i < aa.count() ; ++i) {
				const QDomAttr attr = aa.item(i).toAttr();
				if (!ba.contains(attr.name()) || ba.namedItem(attr.name()).nodeValue() != attr.value())
					return here + QStringLiteral(": attribute %1 differs").arg(attr.name());
			}
		}
		const QList<QDomNode> ac = children(a), bc = children(b);
		if (ac.size() != bc.size())
			return here + QStringLiteral(": %1 vs %2 children").arg(ac.size()).arg(bc.size());
		for (int i = 0 ; i < ac.size() ; ++i) {
			const QString d = difference(ac.at(i), bc.at(i), here + QStringLiteral("[%1]").arg(i));
			if (!d.isEmpty()) return d;
		}
		return {};
	}

	static QByteArray read(const QString &path)
	{
		QFile f(path);
		return f.open(QIODevice::ReadOnly) ? f.readAll() : QByteArray();
	}

	static QList<QetZip::Entry> splitFile(const QString &path, QDomDocument *original)
	{
		QString error;
		if (!QetContainer::parse(read(path), original, &error)) return {};
		return QetContainer::split(*original, QStringLiteral("tst_qetcontainer"), &error);
	}

private slots:
	void sameDocumentBack_data()
	{
		QTest::addColumn<QString>("file");
		QStringList dirs{QStringLiteral(QET_EXAMPLES_DIR)};
		const QString corpus = qEnvironmentVariable("QET_CONTAINER_CORPUS");
		if (!corpus.isEmpty()) dirs << corpus;
		for (const QString &dir : dirs) {
			QDirIterator it(dir, {QStringLiteral("*.qet")}, QDir::Files, QDirIterator::Subdirectories);
			QStringList files;
			while (it.hasNext()) files << it.next();
			files.sort();
			for (const QString &f : files)
				QTest::newRow(qPrintable(QDir(dir).relativeFilePath(f))) << f;
		}
	}
	void sameDocumentBack()
	{
		QFETCH(QString, file);
		QDomDocument original;
		QString error;
		if (!QetContainer::parse(read(file), &original, &error))
			QSKIP(qPrintable(QStringLiteral("not readable as XML, as QElectroTech finds too: ") + error));
		const QList<QetZip::Entry> entries = QetContainer::split(original, QString(), &error);
		QVERIFY2(!entries.isEmpty(), qPrintable(error));
		QCOMPARE(entries.first().name, QStringLiteral("mimetype"));

		QList<QetZip::Entry> unzipped;
		QVERIFY2(QetZip::fromBytes(QetZip::toBytes(entries, &error), &unzipped, &error), qPrintable(error));
		QDomDocument back;
		QVERIFY2(QetContainer::join(unzipped, &back, &error), qPrintable(error));
		const QString d = difference(original.documentElement(), back.documentElement(), QString());
		QVERIFY2(d.isEmpty(), qPrintable(d));
	}

	// The folio pictures leave the folios, once each
	void picturesAreFiles()
	{
		QDomDocument original;
		const QList<QetZip::Entry> entries = splitFile(
					QStringLiteral(QET_EXAMPLES_DIR "/weneedpolonez-Polonez_MR89_wiring_diagram.qet"), &original);
		QVERIFY(!entries.isEmpty());
		int pictures = 0;
		for (const QetZip::Entry &e : entries) {
			if (e.name.startsWith(QStringLiteral("images/"))) {
				++pictures;
				QVERIFY(e.data.startsWith("\x89PNG"));
				QVERIFY(!e.compress);
			}
			if (e.name.startsWith(QStringLiteral("folios/")))
				QVERIFY2(!e.data.contains("iVBORw0KGgo"), "a folio still holds a PNG in base64");
		}
		QVERIFY(pictures > 0);
		QVERIFY(pictures < 121);   // the 121 placed pictures repeat a few files
	}

	// A file whose manifest needs a later reader is refused, not half read
	void laterFormatRefused()
	{
		QDomDocument original;
		QList<QetZip::Entry> entries = splitFile(QStringLiteral(QET_EXAMPLES_DIR "/perceuse.qet"), &original);
		QVERIFY(!entries.isEmpty());
		for (QetZip::Entry &e : entries)
			if (e.name == QLatin1String("manifest.xml"))
				e.data.replace("min-reader=\"1\"", "min-reader=\"9\"");
		QDomDocument back;
		QString error;
		QVERIFY(!QetContainer::join(entries, &back, &error));
		QVERIFY2(error.contains(QStringLiteral("later")), qPrintable(error));
	}

	void missingPartRefused()
	{
		QDomDocument original;
		QList<QetZip::Entry> entries = splitFile(QStringLiteral(QET_EXAMPLES_DIR "/perceuse.qet"), &original);
		for (int i = 0 ; i < entries.size() ; ++i)
			if (entries.at(i).name.startsWith(QStringLiteral("folios/"))) { entries.removeAt(i); break; }
		QDomDocument back;
		QString error;
		QVERIFY(!QetContainer::join(entries, &back, &error));
		QVERIFY2(error.contains(QStringLiteral("missing")), qPrintable(error));
	}

	void notAProjectRefused()
	{
		QDomDocument back;
		QString error;
		QVERIFY(!QetContainer::join({{QStringLiteral("mimetype"), "application/zip", false}}, &back, &error));
	}
};

QTEST_APPLESS_MAIN(tst_qetcontainer)

#include "tst_qetcontainer.moc"
