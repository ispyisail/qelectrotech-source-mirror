/*
	Copyright 2006-2026 The QElectroTech Team
	This file is part of QElectroTech.

	QElectroTech is free software: you can redistribute it and/or modify
	it under the terms of the GNU General Public License as published by
	the Free Software Foundation, either version 2 of the License, or
	(at your option) any later version.

	QElectroTech is distributed in the hope that it will be useful,
	but WITHOUT ANY WARRANTY; without even the implied warranty of
	MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
	GNU General Public License for more details.

	You should have received a copy of the GNU General Public License
	along with QElectroTech.  If not, see <http://www.gnu.org/licenses/>.
*/
#include "dataBase/projectdatabase.h"
#include "diagram.h"
#include "drawinglayers/drawinglayers.h"
#include "qetapptest.h"
#include "qetgraphicsitem/independenttextitem.h"
#include "qetgraphicsitem/qetshapeitem.h"
#include "qetproject.h"
#include "qetresult.h"
#include "shownkinds.h"
#include "undocommand/drawinglayerscommand.h"

#include <QFile>
#include <QHash>
#include <QTemporaryDir>
#include <QtTest>

/**
	Layers of a folio's free drawing: kept with the project, hiding what is
	on them, a project without any saving as before.
*/
class tst_drawinglayers : public QObject
{
	Q_OBJECT
	QTemporaryDir m_dir;

	static DrawingLayers::Set twoLayers(bool first = true, bool second = true)
	{
		DrawingLayers::Set set;
		set.layers = {{QStringLiteral("Quote"), first}, {QStringLiteral("Mounting"), second}};
		set.groups = {{QStringLiteral("For the customer"), {QStringLiteral("Quote")}}};
		return set;
	}

	static QetShapeItem *line(Diagram *folio, const QString &layer)
	{
		auto *shape = new QetShapeItem(QPointF(10, 10), QPointF(100, 10), QetShapeItem::Line);
		folio->addItem(shape);
		DrawingLayers::setLayerOf(shape, layer);
		return shape;
	}

	static IndependentTextItem *text(Diagram *folio, const QString &layer)
	{
		auto *item = new IndependentTextItem(QStringLiteral("NOTE"));
		folio->addItem(item);
		DrawingLayers::setLayerOf(item, layer);
		return item;
	}

  private slots:
	void initTestCase()
	{
		QVERIFY(m_dir.isValid());
		QETProject::setBackupEnabled(false);
	}

	void setsReadBackAndGroupsShow()
	{
		QDomDocument doc;
		const DrawingLayers::Set read = DrawingLayers::Set::fromXml(twoLayers(true, false).toXml(doc));
		QVERIFY(read == twoLayers(true, false));
		QVERIFY(read.isVisible(QStringLiteral("Quote")));
		QVERIFY(!read.isVisible(QStringLiteral("Mounting")));
		QVERIFY(read.isVisible(QStringLiteral("Unknown")));    //a layer the project does not know
		const auto shown = twoLayers(false, true).showing(read.groups.first());
		QVERIFY(shown.isVisible(QStringLiteral("Quote")));
		QVERIFY(!shown.isVisible(QStringLiteral("Mounting")));
	}

	void onlyFreeDrawingIsOnALayer()
	{
		QETProject project;
		Diagram *folio = project.addNewDiagram();
		QVERIFY(DrawingLayers::canBeOnLayer(line(folio, QString())));
		QVERIFY(DrawingLayers::canBeOnLayer(text(folio, QString())));
		QGraphicsRectItem other;
		QVERIFY(!DrawingLayers::canBeOnLayer(&other));
	}

	void hidingALayerHidesWhatIsOnIt()
	{
		QETProject project;
		Diagram *folio = project.addNewDiagram();
		project.setDrawingLayers(twoLayers());
		auto *quote = line(folio, QStringLiteral("Quote"));
		auto *mounting = text(folio, QStringLiteral("Mounting"));
		auto *free_item = line(folio, QString());
		project.setDrawingLayers(twoLayers(false, true));
		QVERIFY(!quote->isVisible());
		QVERIFY(mounting->isVisible());
		QVERIFY(free_item->isVisible());
		QVERIFY(DrawingLayers::isHidden(quote));
		QVERIFY(!DrawingLayers::isHidden(free_item));
		project.setDrawingLayers(twoLayers());
		QVERIFY(quote->isVisible());
	}

	void layersAndViewShowEachOnlyVeto()
	{
		QETProject project;
		Diagram *folio = project.addNewDiagram();
		project.setDrawingLayers(twoLayers());
		auto *shape = line(folio, QStringLiteral("Quote"));
			//Off by its layer: showing its kind again does not bring it back
		project.setDrawingLayers(twoLayers(false, true));
		ShownKinds::setShown(ShownKinds::Shapes, false);
		ShownKinds::apply(folio, ShownKinds::Shapes);
		ShownKinds::setShown(ShownKinds::Shapes, true);
		ShownKinds::apply(folio, ShownKinds::Shapes);
		QVERIFY(!shape->isVisible());
		project.setDrawingLayers(twoLayers());
		QVERIFY(shape->isVisible());
	}

	void keptWithTheProject_data()
	{
		QTest::addColumn<QString>("file");
		QTest::newRow("qet") << QStringLiteral("layers.qet");
		QTest::newRow("qetdb") << QStringLiteral("layers.qetdb");
	}

	void keptWithTheProject()
	{
		QFETCH(QString, file);
		const QString path = m_dir.filePath(file);
		{
			QETProject project;
			Diagram *folio = project.addNewDiagram();
			project.setDrawingLayers(twoLayers(false, true));
			line(folio, QStringLiteral("Quote"));
			text(folio, QStringLiteral("Mounting"));
			line(folio, QString());
			project.setFilePath(path);
			QVERIFY(project.write().isOk());
		}
		QETProject again(path);
		QVERIFY(again.drawingLayers() == twoLayers(false, true));
		again.loadFolios();
		int hidden = 0, on_quote = 0, on_mounting = 0, none = 0;
		for (QGraphicsItem *item : again.diagrams().first()->items()) {
			if (!DrawingLayers::canBeOnLayer(item)) continue;
			const QString layer = DrawingLayers::layerOf(item);
			on_quote += layer == QLatin1String("Quote");
			on_mounting += layer == QLatin1String("Mounting");
			none += layer.isEmpty();
			hidden += !item->isVisible();
		}
		QCOMPARE(on_quote, 1);
		QCOMPARE(on_mounting, 1);
		QCOMPARE(none, 1);
		QCOMPARE(hidden, 1);
	}

	void aProjectWithoutLayersSavesAsBefore()
	{
		QETProject project;
		Diagram *folio = project.addNewDiagram();
		line(folio, QString());
		const QString path = m_dir.filePath(QStringLiteral("none.qet"));
		project.setFilePath(path);
		QVERIFY(project.write().isOk());
		QFile f(path);
		QVERIFY(f.open(QIODevice::ReadOnly));
		const QByteArray saved = f.readAll();
		QVERIFY(!saved.contains("<layers"));
		QVERIFY(!saved.contains("layer="));
	}

	void undoGivesBackLayersAndItems()
	{
		QETProject project;
		Diagram *folio = project.addNewDiagram();
		project.setDrawingLayers(twoLayers());
		auto *shape = line(folio, QString());
		QHash<QGraphicsObject *, QString> items;
		items.insert(shape, QStringLiteral("Quote"));
		DrawingLayersCommand command(&project, twoLayers(false, true), items);
		command.redo();
		QCOMPARE(DrawingLayers::layerOf(shape), QStringLiteral("Quote"));
		QVERIFY(!shape->isVisible());
		command.undo();
		QCOMPARE(DrawingLayers::layerOf(shape), QString());
		QVERIFY(shape->isVisible());
		QVERIFY(project.drawingLayers() == twoLayers());
	}
};

QET_APP_TEST_MAIN(tst_drawinglayers)
#include "tst_drawinglayers.moc"
