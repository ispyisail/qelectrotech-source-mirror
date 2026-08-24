/*
	Copyright 2006-2025 The QElectroTech Team
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
#include "cli_export.h"

#include "bordertitleblock.h"
#include "conductornumexport.h"
#include "conductorproperties.h"
#include "dataBase/projectdatabase.h"
#include "diagram.h"
#include "diagramcommands.h"
#include "diagramcontent.h"
#include "diagramcontext.h"
#include "elementsmover.h"
#include "pdf_links.h"
#include "qetgraphicsitem/conductor.h"
#include "qetgraphicsitem/conductortextitem.h"
#include "qetgraphicsitem/element.h"
#include "qetgraphicsitem/terminal.h"
#include "qet.h"
#include "qetproject.h"
#include "titleblockproperties.h"
#include "undocommand/changeelementinformationcommand.h"
#include "undocommand/deleteqgraphicsitemcommand.h"
#include "undocommand/linkelementcommand.h"
#include "undocommand/rotateselectioncommand.h"
#include "utils/conductorcreator.h"
#include "undocommand/movegraphicsitemcommand.h"
#include "undocommand/rotatetextscommand.h"
#include "wiringlistexport.h"

// Private Qt PDF engine for drawHyperlink() — see pdf_links / projectprintwindow.
#include <private/qpdf_p.h>

#include <QDir>
#include <QDirIterator>
#include <QDomDocument>
#include <QDate>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMap>
#include <QPageLayout>
#include <QPair>
#include <QPainter>
#include <QPolygonF>
#include <QPdfWriter>
#include <QSet>
#include <QSqlError>
#include <QSqlQuery>
#include <QSvgGenerator>
#include <QTextStream>
#include <QTransform>

namespace {

QTextStream out(stdout);
QTextStream err(stderr);

/// All CLI option flags, mapped to a short format name.
const QHash<QString, QString> &exportFlags()
{
	static const QHash<QString, QString> flags {
		{"--export-pdf", "pdf"},
		{"--export-png", "png"},
		{"--export-svg", "svg"},
		{"--export-cables", "cables"},
		{"--export-wires", "wires"},
		{"--export-bom", "bom"},
		{"--export-nets", "nets"},
		{"--export-links", "links"},
		{"--info", "info"},
		{"--check-elements", "check"},
		{"--resave", "resave"},
		{"--set-titleblock", "settb"},
		{"--test-ops", "testops"},
	};
	return flags;
}

/// Device tag of an element ("K1", "Q55"), falling back to its name.
QString elementLabel(Element *element)
{
	const QString label = element->elementInformations()["label"].toString();
	return label.isEmpty() ? element->name() : label;
}

/// Pixel rect of a diagram's border + title block (the printable page area).
QRect diagramRect(Diagram *diagram)
{
	QRectF r = diagram->border_and_titleblock.borderAndTitleBlockRect();
	r.adjust(0, 0, 1, 1); // include the 1px border line
	return r.toAlignedRect();
}

/// A filesystem-safe per-diagram file stem: "01_Title".
QString diagramStem(Diagram *diagram, int index)
{
	QString title = diagram->title();
	title.replace(QRegularExpression("[^\\w \\-]"), "_");
	title = title.simplified();
	if (title.isEmpty())
		title = "diagram";
	return QStringLiteral("%1_%2")
		.arg(index, 2, 10, QChar('0'))
		.arg(title);
}

/// Render @p diagram into @p painter, fitting @p target to the page rect.
void renderDiagram(Diagram *diagram, QPainter &painter, const QRectF &target)
{
	const QRect source = diagramRect(diagram);
	// Export without the editor grid: drawBackground() only paints it when
	// draw_grid_ is set (default true), so toggle it off around the render
	// and restore it afterwards.
	const bool was_drawing_grid = diagram->displayGrid();
	const bool was_drawing_guides = diagram->displayGuides();
	diagram->setDisplayGrid(false);
	diagram->setDisplayGuides(false);
	diagram->render(&painter, target, source, Qt::KeepAspectRatio);
	diagram->setDisplayGrid(was_drawing_grid);
	diagram->setDisplayGuides(was_drawing_guides);
}

int exportPdf(QETProject &project, const QString &output)
{
	const QList<Diagram *> diagrams = project.diagrams();
	if (diagrams.isEmpty()) {
		err << "No diagrams to export.\n";
		return 1;
	}

	// Page numbers (1-based) for cross-reference hyperlink targets: each
	// diagram is exactly one page in the CLI export (no tiling).
	QMap<Diagram *, int> pageMap;
	for (int i = 0; i < diagrams.size(); ++i)
		pageMap.insert(diagrams.at(i), i + 1);

	QPdfWriter writer(output);
	writer.setCreator("QElectroTech");
	writer.setResolution(96);

	QPainter painter;
	bool first = true;
	for (Diagram *diagram : diagrams) {
		const QRect r = diagramRect(diagram);
		// Match the page to the diagram (in points: 1px @ 96dpi = 0.75pt).
		const QPageSize page(QSizeF(r.width() * 72.0 / 96.0,
									r.height() * 72.0 / 96.0),
							 QPageSize::Point);
		writer.setPageSize(page);
		writer.setPageMargins(QMarginsF(0, 0, 0, 0));

		if (first) {
			if (!painter.begin(&writer)) {
				err << "Cannot open '" << output << "' for writing.\n";
				return 1;
			}
			first = false;
		} else {
			writer.newPage();
		}
		const QRectF target(0, 0,
							writer.width(), writer.height());
		renderDiagram(diagram, painter, target);

		// Inject clickable cross-reference / folio-report hyperlinks for this
		// page.  The geometry is rebuilt from the QPdfWriter (not a QPrinter):
		// render() anchors the diagram top-left with KeepAspectRatio, and the
		// page is sized to the diagram so the scale is ~1.
		if (auto *engine = dynamic_cast<QPdfEngine *>(painter.paintEngine())) {
			const QRectF source(r);
			const qreal s = qMin(target.width()  / source.width(),
								 target.height() / source.height());
			QTransform fit;
			fit.translate(target.x(), target.y());
			fit.scale(s, s);
			fit.translate(-source.x(), -source.y());

			// Device pixels -> PDF points, replicating the engine's page matrix
			// (72/resolution scale + Y flip; zero margins -> no paint offset).
			const qreal pt_scale = 72.0 / writer.resolution();
			const qreal fullH_pt = writer.pageLayout().fullRectPoints().height();
			const bool  fullPageMode =
				(writer.pageLayout().mode() == QPageLayout::FullPageMode);
			const QRect paintPx =
				writer.pageLayout().paintRectPixels(writer.resolution());

			PdfLinks::PageGeometry geom;
			geom.sceneToDevice = fit;
			geom.target        = target;
			geom.pageBounds    = QRectF(0, 0, target.width(), target.height());
			geom.devToPdf = [=](const QPointF &d) -> QPointF {
				qreal dx = d.x(), dy = d.y();
				if (!fullPageMode) { dx += paintPx.left(); dy += paintPx.top(); }
				return QPointF(pt_scale * dx, fullH_pt - pt_scale * dy);
			};
			geom.sourceRectOf = [](Diagram *dg) {
				return QRectF(diagramRect(dg));
			};
			PdfLinks::injectCrossRefLinks(engine, diagram, geom, pageMap, output);
		}
	}
	painter.end();

	// Rewrite the URI link annotations into native internal GoTo actions, so
	// the cross-references jump inside the document in any PDF viewer.
	PdfLinks::convertUriToGoTo(output);

	out << "Exported " << diagrams.size() << " page(s) -> " << output << "\n";
	return 0;
}

int exportImages(QETProject &project, const QString &format,
				 const QString &out_dir)
{
	const QList<Diagram *> diagrams = project.diagrams();
	if (diagrams.isEmpty()) {
		err << "No diagrams to export.\n";
		return 1;
	}
	QDir().mkpath(out_dir);

	int index = 0;
	for (Diagram *diagram : diagrams) {
		++index;
		const QRect r = diagramRect(diagram);
		const QString path = QDir(out_dir).filePath(
			diagramStem(diagram, index) + "." + format);

		if (format == "svg") {
			QSvgGenerator gen;
			gen.setFileName(path);
			gen.setSize(r.size());
			gen.setViewBox(QRect(0, 0, r.width(), r.height()));
			gen.setTitle(diagram->title());
			QPainter painter(&gen);
			renderDiagram(diagram, painter, QRectF(QPointF(0, 0), r.size()));
			painter.end();
		} else { // png
			QImage image(r.size(), QImage::Format_ARGB32);
			image.fill(Qt::white);
			QPainter painter(&image);
			painter.setRenderHint(QPainter::Antialiasing, true);
			renderDiagram(diagram, painter, QRectF(QPointF(0, 0), r.size()));
			painter.end();
			if (!image.save(path)) {
				err << "Failed to write '" << path << "'.\n";
				return 1;
			}
		}
		out << "  " << path << "\n";
	}
	out << "Exported " << diagrams.size() << " diagram(s) -> " << out_dir << "\n";
	return 0;
}

int exportCsv(QETProject &project, const QString &format, const QString &output)
{
	QString csv;
	if (format == "cables") {
		WiringListExport wle(&project, nullptr);
		csv = wle.toCsvString();
	} else { // wires
		ConductorNumExport cne(&project, nullptr);
		csv = cne.wiresNum();
	}
	if (csv.isEmpty()) {
		err << "Nothing to export (empty list).\n";
		return 1;
	}

	QFile file(output);
	if (!file.open(QIODevice::WriteOnly | QIODevice::Text)) {
		err << "Cannot open '" << output << "' for writing.\n";
		return 1;
	}
	QTextStream fout(&file);
	fout << csv;
	file.close();
	out << "Exported " << format << " list -> " << output << "\n";
	return 0;
}

/// Quote a field for CSV output (RFC-4180 style, ';' delimiter).
QString csvField(const QString &value)
{
	if (value.contains(';') || value.contains('"')
		|| value.contains('\n') || value.contains('\r')) {
		QString v = value;
		v.replace('"', "\"\"");
		return '"' % v % '"';
	}
	return value;
}

/// Bill of materials: one row per element, key component-data fields.
/// Pulls from QET's own project database (the same source as the GUI BOM
/// export), so the output matches what the editor produces.
int exportBom(QETProject &project, const QString &output)
{
	// The project database is built lazily; force a (re)build before querying.
	project.dataBase()->updateDB();

	static const QStringList columns {
		"label", "designation", "manufacturer", "manufacturer_reference",
		"quantity", "location", "function", "title", "folio"
	};

	QSqlQuery query = project.dataBase()->newQuery(
		"SELECT " % columns.join(", ") %
		" FROM element_nomenclature_view ORDER BY label");
	if (!query.exec()) {
		err << "BOM query failed: " << query.lastError().text() << "\n";
		return 1;
	}

	QString csv = columns.join(";") % "\n";
	int rows = 0;
	while (query.next()) {
		QStringList values;
		for (int i = 0; i < columns.size(); ++i)
			values << csvField(query.value(i).toString());
		csv += values.join(";") % "\n";
		++rows;
	}

	QFile file(output);
	if (!file.open(QIODevice::WriteOnly | QIODevice::Text)) {
		err << "Cannot open '" << output << "' for writing.\n";
		return 1;
	}
	QTextStream fout(&file);
	fout << csv;
	file.close();
	out << "Exported " << rows << " component(s) -> " << output << "\n";
	return 0;
}

/// Count terminals on @p element that no conductor connects to.
int freeTerminals(Element *element)
{
	int free = 0;
	const QList<Terminal *> terminals = element->terminals();
	for (Terminal *t : terminals)
		if (t->conductorsCount() == 0)
			++free;
	return free;
}

/// Structural ground-truth dump of a project, as JSON, to stdout (or a file).
/// Uses QET's own loaded model, so it reports what the editor actually sees:
/// per-page element / conductor counts and unconnected terminals.
int exportInfo(QETProject &project, const QString &output)
{
	const QList<Diagram *> diagrams = project.diagrams();

	int total_elements = 0, total_conductors = 0, total_free = 0;
	QJsonArray pages;
	int index = 0;
	for (Diagram *diagram : diagrams) {
		++index;
		const QList<Element *> elements = diagram->elements();
		const int conductors = diagram->conductors().size();
		int page_free = 0;
		for (Element *e : elements)
			page_free += freeTerminals(e);

		const QRect r = diagramRect(diagram);
		QJsonObject page;
		page["index"]             = index;
		page["title"]             = diagram->title();
		page["folio"]             = QStringLiteral("%1 of %2")
									 .arg(index).arg(diagrams.size());
		page["width_px"]          = r.width();
		page["height_px"]         = r.height();
		page["elements"]          = elements.size();
		page["conductors"]        = conductors;
		page["free_terminals"]    = page_free;
		pages.append(page);

		total_elements   += elements.size();
		total_conductors += conductors;
		total_free       += page_free;
	}

	QJsonObject root;
	root["project"]    = project.title();
	root["diagrams"]   = diagrams.size();
	root["elements"]   = total_elements;
	root["conductors"] = total_conductors;
	root["free_terminals"] = total_free;
	root["pages"]      = pages;

	const QByteArray json =
		QJsonDocument(root).toJson(QJsonDocument::Indented);

	if (output.isEmpty()) {
		out << QString::fromUtf8(json);
	} else {
		QFile file(output);
		if (!file.open(QIODevice::WriteOnly | QIODevice::Text)) {
			err << "Cannot open '" << output << "' for writing.\n";
			return 1;
		}
		file.write(json);
		file.close();
		out << "Wrote project info -> " << output << "\n";
	}
	return 0;
}

/// Validate one .elmt file against QET's element schema.
/// @return 0 = OK, 1 = warning (loads but suspicious), 2 = failure.
int checkOneElement(const QString &path)
{
	QFile file(path);
	if (!file.open(QIODevice::ReadOnly)) {
		out << "FAIL  " << path << "  (cannot open)\n";
		return 2;
	}
	QDomDocument doc;
#if QT_VERSION >= QT_VERSION_CHECK(6, 5, 0)
	if (const auto result = doc.setContent(&file); !result) {
		file.close();
		out << "FAIL  " << path << "  (XML error line "
			<< result.errorLine << ": " << result.errorMessage << ")\n";
		return 2;
	}
#else
	QString error;
	int line = 0;
	if (!doc.setContent(&file, &error, &line)) {
		file.close();
		out << "FAIL  " << path << "  (XML error line "
			<< line << ": " << error << ")\n";
		return 2;
	}
#endif
	file.close();

	const QDomElement root = doc.documentElement();
	if (root.tagName() != "definition" || root.attribute("type") != "element") {
		out << "FAIL  " << path << "  (root is not <definition type=\"element\">)\n";
		return 2;
	}

	bool w_ok = false, h_ok = false;
	const double w = root.attribute("width").toDouble(&w_ok);
	const double h = root.attribute("height").toDouble(&h_ok);
	if (!w_ok || !h_ok || w == 0 || h == 0) {
		out << "FAIL  " << path << "  (missing/zero bounding box "
			<< root.attribute("width") << "x"
			<< root.attribute("height") << ")\n";
		return 2;
	}

	const int terminals = root.elementsByTagName("terminal").count();

	// Negative dimensions are malformed but QET still loads them; surface as a
	// warning rather than a failure so this agrees with QET's own loader.
	if (w < 0 || h < 0) {
		out << "WARN  " << path << "  (negative bounding box "
			<< w << "x" << h << ", " << terminals << " terminals)\n";
		return 1;
	}

	if (terminals == 0) {
		out << "WARN  " << path << "  (loads, but 0 terminals)\n";
		return 1;
	}

	out << "OK    " << path << "  (" << terminals << " terminals)\n";
	return 0;
}

/// Validate a single .elmt file or every .elmt under a directory.
int checkElements(const QString &path)
{
	QStringList files;
	const QFileInfo info(path);
	if (info.isDir()) {
		QDirIterator it(path, {"*.elmt"}, QDir::Files,
						QDirIterator::Subdirectories);
		while (it.hasNext())
			files << it.next();
		files.sort();
	} else if (info.isFile()) {
		files << path;
	} else {
		err << "Not found: " << path << "\n";
		return 2;
	}

	if (files.isEmpty()) {
		err << "No .elmt files found under: " << path << "\n";
		return 2;
	}

	int warnings = 0, failures = 0;
	for (const QString &f : files) {
		const int r = checkOneElement(f);
		if (r == 1) ++warnings;
		else if (r == 2) ++failures;
	}
	out << files.size() << " file(s), " << warnings
		<< " warning(s), " << failures << " failure(s)\n";
	return failures > 0 ? 1 : 0;
}

/// Map every element in the project to its 1-based folio (page) position.
QHash<Element *, int> folioIndex(QETProject &project)
{
	QHash<Element *, int> folio;
	int index = 0;
	const QList<Diagram *> diagrams = project.diagrams();
	for (Diagram *diagram : diagrams) {
		++index;
		const QList<Element *> elements = diagram->elements();
		for (Element *e : elements)
			folio.insert(e, index);
	}
	return folio;
}

/// Electrical nets: groups of terminals joined into one potential.
/// Walks QET's own potential graph, so each net is a connected component
/// of terminals across all folios. The ground truth for connectivity.
int exportNets(QETProject &project, const QString &output)
{
	const QHash<Element *, int> folio = folioIndex(project);

	QList<Conductor *> all_conductors;
	const QList<Diagram *> diagrams = project.diagrams();
	for (Diagram *diagram : diagrams)
		all_conductors << diagram->conductors();

	QSet<Conductor *> visited;
	QJsonArray nets;
	int net_no = 0;
	for (Conductor *c : all_conductors) {
		if (visited.contains(c))
			continue;

		// The whole potential this conductor belongs to. relatedPotential-
		// Conductors() also fills t_list with every terminal in the net
		// (following folio reports and terminal blocks too).
		QList<Terminal *> t_list;
		QSet<Conductor *> group = c->relatedPotentialConductors(true, &t_list);
		group.insert(c);
		for (Conductor *g : group)
			visited.insert(g);
		if (c->terminal1) t_list << c->terminal1;
		if (c->terminal2) t_list << c->terminal2;

		// Wire number: smallest non-empty conductor text (deterministic).
		QStringList wire_nos;
		for (Conductor *g : group)
			if (!g->properties().text.isEmpty())
				wire_nos << g->properties().text;
		wire_nos.sort();

		++net_no;
		QJsonArray terminals;
		QSet<Terminal *> seen;
		for (Terminal *t : t_list) {
			if (!t || seen.contains(t))
				continue;
			seen.insert(t);
			Element *pe = t->parentElement();
			QJsonObject to;
			to["element"]  = pe ? elementLabel(pe) : QString();
			to["terminal"] = t->name();
			to["folio"]    = pe ? folio.value(pe, 0) : 0;
			terminals.append(to);
		}
		QJsonObject net;
		net["net"]       = net_no;
		net["wire_no"]   = wire_nos.value(0);
		net["terminals"] = terminals;
		nets.append(net);
	}

	QJsonObject root;
	root["project"] = project.title();
	root["nets"]    = nets.size();
	root["list"]    = nets;

	QFile file(output);
	if (!file.open(QIODevice::WriteOnly | QIODevice::Text)) {
		err << "Cannot open '" << output << "' for writing.\n";
		return 1;
	}
	file.write(QJsonDocument(root).toJson(QJsonDocument::Indented));
	file.close();
	out << "Exported " << nets.size() << " net(s) -> " << output << "\n";
	return 0;
}

/// Cross-references: each linkable element (coil / contact / report) and the
/// elements it links to, flagging masters/slaves with no link as unresolved.
int exportLinks(QETProject &project, const QString &output)
{
	const QHash<Element *, int> folio = folioIndex(project);

	QString csv("element;link_type;linked_to;folio;status\n");
	int linkable = 0, unresolved = 0;

	const QList<Diagram *> diagrams = project.diagrams();
	for (Diagram *diagram : diagrams) {
		const QList<Element *> elements = diagram->elements();
		for (Element *e : elements) {
			if (e->linkType() == Element::Simple)
				continue;
			++linkable;

			const QList<Element *> linked = e->linkedElements();
			QStringList names;
			for (Element *le : linked)
				names << elementLabel(le) % "(f"
					   % QString::number(folio.value(le, 0)) % ")";

			QString status = "linked";
			if ((e->linkType() == Element::Master
				 || e->linkType() == Element::Slave)
				&& linked.isEmpty()) {
				status = "UNRESOLVED";
				++unresolved;
			}

			csv += csvField(elementLabel(e)) % ";"
				 % e->linkTypeToString() % ";"
				 % csvField(names.join(", ")) % ";"
				 % QString::number(folio.value(e, 0)) % ";"
				 % status % "\n";
		}
	}

	QFile file(output);
	if (!file.open(QIODevice::WriteOnly | QIODevice::Text)) {
		err << "Cannot open '" << output << "' for writing.\n";
		return 1;
	}
	QTextStream fout(&file);
	fout << csv;
	file.close();
	out << "Exported " << linkable << " linkable element(s), "
		<< unresolved << " unresolved -> " << output << "\n";
	return 0;
}

/// Round-trip: load the project and write its XML back out, so an external
/// diff can reveal markup QET silently normalises (tolerated-but-invalid XML).
int resaveProject(QETProject &project, const QString &output)
{
	const QDomDocument doc = project.toXml();
	QFile file(output);
	if (!file.open(QIODevice::WriteOnly | QIODevice::Text)) {
		err << "Cannot open '" << output << "' for writing.\n";
		return 1;
	}
	QTextStream fout(&file);
	fout << doc.toString(4);
	file.close();
	out << "Re-saved project -> " << output << "\n";
	return 0;
}

/// Resolve a "select" op's uuid list against @p diagram's elements, clearing
/// and rebuilding the selection. Unknown uuids are reported, not fatal --
/// a partially-matched selection is still meaningful to the caller.
void applySelect(Diagram *diagram, const QJsonArray &uuids)
{
	diagram->clearSelection();
	const QList<Element *> elements = diagram->elements();
	for (const QJsonValue &v : uuids) {
		const QUuid target(v.toString());
		bool found = false;
		for (Element *e : elements) {
			if (e->uuid() == target) {
				e->setSelected(true);
				found = true;
				break;
			}
		}
		if (!found) {
			err << "test-ops: select -- uuid not found in diagram: "
				<< v.toString() << "\n";
		}
	}
}

/// Resolve a "select_rect" op: select every element whose scene bounding
/// rect intersects the given rectangle, clearing and rebuilding the
/// selection first.
///
/// Matches QET's actual rubber-band behaviour, not an assumption: QET sets
/// QGraphicsView::RubberBandDrag on DiagramView (diagramview.cpp:322) and
/// never calls setRubberBandSelectionMode(), so Qt's documented default
/// applies -- Qt::IntersectsItemShape, items whose shape intersects the
/// drag rectangle. This op approximates "shape" with sceneBoundingRect()
/// rather than the exact painted QPainterPath: for QET's elements (mostly
/// rectangular symbol bodies) the two agree in the overwhelming majority of
/// cases, and the difference only matters for a rectangle edge that clips
/// a non-rectangular element's corner -- a real but narrow gap, stated here
/// rather than left implicit.
void applySelectRect(Diagram *diagram, const QJsonObject &rectObj)
{
	const QRectF rect(
		rectObj.value("x").toDouble(), rectObj.value("y").toDouble(),
		rectObj.value("w").toDouble(), rectObj.value("h").toDouble()
	);
	diagram->clearSelection();
	int matched = 0;
	for (Element *e : diagram->elements()) {
		if (e->sceneBoundingRect().intersects(rect)) {
			e->setSelected(true);
			++matched;
		}
	}
	out << "test-ops: select_rect -- " << matched << " element(s) matched "
		<< rect.x() << "," << rect.y() << " " << rect.width() << "x"
		<< rect.height() << "\n";
}

/// Mirrors LinkElementCommand::redo()'s report-report PotentialSelectorDialog
/// trigger (undocommand/linkelementcommand.cpp) -- checked source before
/// relying on it, same discipline connect_rect's guard used.
///
/// A first version of this function checked ONLY primary's own pre-existing
/// potential (mirroring redo()'s c_list construction line-for-line) and was
/// proven wrong by a live hang, not caught by reading the source a second
/// time: redo() calls makeLink() -- which actually applies the element-level
/// link -- BEFORE running this check, so relatedPotentialConductors() at
/// that point traverses THROUGH the just-made link (a folio-report link is
/// an electrical continuation, so the potential graph crosses it) and sees
/// both sides. This guard runs BEFORE any link is made (that's the whole
/// point -- decide whether to make it), so relatedPotentialConductors()
/// here only ever sees primary's side, silently under-approximating the
/// real check and letting a genuine trigger through. Fixed by unioning
/// BOTH sides' pre-existing potentials directly instead of relying on a
/// not-yet-applied link to connect them -- verified against the exact
/// fixture that hung under the first version, not just re-derived from
/// reading the source again.
bool wouldShowPotentialSelectorDialog(Element *primary, const QList<Element *> &linked_after)
{
	if (!(primary->linkType() & Element::AllReport)) return false;
	if (primary->conductors().isEmpty()) return false;
	if (linked_after.isEmpty()) return false;

	QSet<Conductor *> c_list;
	c_list << primary->conductors().first();
	for (Conductor *c : primary->conductors().first()->relatedPotentialConductors())
		c_list << c;
	for (Element *linked : linked_after) {
		if (linked->conductors().isEmpty()) continue;
		c_list << linked->conductors().first();
		for (Conductor *c : linked->conductors().first()->relatedPotentialConductors())
			c_list << c;
	}
	if (c_list.size() < 2) return false;

	QStringList str_txt, str_funct, str_tens;
	for (Conductor *c : std::as_const(c_list)) {
		str_txt   << c->properties().text;
		str_funct << c->properties().m_function;
		str_tens  << c->properties().m_tension_protocol;
		str_tens  << c->properties().m_wire_color;
		str_tens  << c->properties().m_wire_section;
	}
	return !QET::eachStrIsEqual(str_txt) || !QET::eachStrIsEqual(str_funct)
		|| !QET::eachStrIsEqual(str_tens);
}

/// Resolve a "link" op: link uuids[0] (the "primary"/edited element, matching
/// LinkElementCommand's own model -- the element the command is constructed
/// for) to every other element in uuids, via LinkElementCommand -- the same
/// class the GUI's cross-reference linking uses. Requires at least 2 uuids.
///
/// Validates every candidate with LinkElementCommand::isLinkable() up front
/// and refuses (no push) if any candidate isn't linkable, rather than
/// relying on setUpNewLink()'s own behavior of silently skipping
/// non-linkable candidates -- a caller asking to link a specific pair wants
/// to know when that didn't happen, not a partial, silently-smaller link.
bool applyLink(Diagram *diagram, const QJsonArray &uuids)
{
	if (uuids.size() < 2) {
		err << "test-ops: link -- requires at least 2 uuids (primary + one or more to link).\n";
		return false;
	}

	QList<Element *> resolved;
	const QList<Element *> elements = diagram->elements();
	for (const QJsonValue &v : uuids) {
		const QUuid target(v.toString());
		Element *found = nullptr;
		for (Element *e : elements) {
			if (e->uuid() == target) { found = e; break; }
		}
		if (!found) {
			err << "test-ops: link -- uuid not found in diagram: " << v.toString() << "\n";
			return false;
		}
		resolved << found;
	}

	Element *primary = resolved.first();
	const QList<Element *> candidates = resolved.mid(1);

	for (Element *c : candidates) {
		if (!LinkElementCommand::isLinkable(primary, c)) {
			err << "test-ops: link -- " << c->uuid().toString()
				<< " is not linkable to " << primary->uuid().toString() << ".\n";
			return false;
		}
	}

	if (wouldShowPotentialSelectorDialog(primary, candidates)) {
		err << "test-ops: link -- linking these reports would show a modal "
			   "properties-reconciliation dialog (differing conductor "
			   "text/function/tension across the merged potential), which "
			   "hangs headless. Refusing rather than hanging.\n";
		return false;
	}

	auto *cmd = new LinkElementCommand(primary);
	cmd->setLink(candidates);
	diagram->undoStack().push(cmd);
	out << "test-ops: link -- linked " << primary->uuid().toString() << " to "
		<< candidates.size() << " element(s).\n";
	return true;
}

/// Resolve a "paste" op: duplicate the current selection, positioning the
/// pasted copy's bounding-rect top-left at (x, y) -- matching
/// Diagram::fromXml()'s own "position" semantics exactly (its doc comment:
/// "the imported elements are positioned in such a way that the upper left
/// corner of the smallest rectangle that can surround them all is at this
/// position").
///
/// Deliberately bypasses the system clipboard DiagramView::copy()/paste()
/// actually use (QApplication::clipboard()) -- checked, not assumed unsafe:
/// a real OS clipboard is exactly the kind of environment-dependent
/// resource that is fragile or unavailable under offscreen/headless
/// operation, the same category of risk --offscreen QPA exists to route
/// around for rendering. Reuses the exact same two calls copy()/paste()
/// make around that clipboard step instead -- diagram->toXml(false, true)
/// (wholeContent=false, is_copy_command=true, identical to what copy()
/// puts on the clipboard) to serialize the current selection, then
/// diagram->fromXml(...) (identical to what paste() does with clipboard
/// text) to import it back in -- so the op exercises the real
/// serialize/import code path, just without the OS clipboard hop in the
/// middle.
///
/// Checked the read-only guard's exact location before relying on it:
/// DiagramView::paste() checks `m_diagram->isReadOnly()` itself (not
/// copy()), so that is checked here explicitly rather than assumed to be
/// enforced somewhere inside fromXml().
bool applyPaste(Diagram *diagram, qreal x, qreal y)
{
	if (diagram->isReadOnly()) {
		err << "test-ops: paste -- diagram is read-only.\n";
		return false;
	}

	QDomDocument doc = diagram->toXml(false, true);
	if (doc.documentElement().isNull()) {
		err << "test-ops: paste -- nothing selected to copy.\n";
		return false;
	}

	DiagramContent content_pasted;
	diagram->fromXml(doc, QPointF(x, y), false, &content_pasted);

	if (!content_pasted.count()) {
		err << "test-ops: paste -- nothing was added.\n";
		return false;
	}

	diagram->clearSelection();
	diagram->undoStack().push(new PasteDiagramCommand(diagram, content_pasted));
	out << "test-ops: paste -- pasted " << content_pasted.count()
		<< " item(s), bounding-rect top-left at " << x << "," << y << "\n";
	return true;
}

/// Resolve a "move" op: translate the current selection by (dx, dy).
///
/// Reuses ElementsMover (elementsmover.h) directly rather than
/// reimplementing conductor-path updates and undo-command construction --
/// it is the same class QET's interactive mouse-drag uses
/// (elementsmover.cpp: beginMovement/continueMovement/endMovement).
/// Checked before using it headless, not assumed safe: MoveGraphicsItemCommand
/// (undocommand/movegraphicsitemcommand.cpp) does NOT apply the position
/// change itself on construction -- its first redo() is a deliberate no-op,
/// because the GUI's live drag has already called setPos() on every item by
/// the time endMovement() constructs and pushes the command. Pushing that
/// command directly, without first moving the items the way
/// continueMovement() does, would silently produce a no-op move with a
/// working-looking undo/redo pair. Driving all three ElementsMover steps
/// avoids that trap entirely. driver_item defaults to nullptr and
/// beginMovement() itself tolerates an empty diagram->views() list, so no
/// QGraphicsView is required.
bool applyMove(Diagram *diagram, qreal dx, qreal dy)
{
	ElementsMover mover;
	if (mover.beginMovement(diagram) < 0) {
		return false; // nothing selected, or nothing movable in the selection
	}
	mover.continueMovement(QPointF(dx, dy));
	mover.endMovement();
	return true;
}

/// Mirrors ConductorCreator::existingPotential() + the "potentials.size()
/// >= 2" check in setUpPropertieToUse() (utils/conductorcreator.cpp) --
/// both private, so reimplemented here from public Terminal/Conductor/
/// Element APIs rather than called directly. Not a guess at the trigger
/// condition: measured on real data first (see the DIAGNOSTIC-TOOLS-PLAN.md
/// commit alongside this one) that a plain rectangle over any populated
/// area of a real wiring diagram hits this in roughly half of cells, not
/// the "narrow edge case" it looks like from the source alone -- a
/// PotentialSelectorDialog under offscreen QPA hangs forever, so this
/// counts distinct existing potentials among @p terminals and reports
/// whether ConductorCreator would show that dialog, so the caller can
/// refuse before ever constructing it.
bool wouldNeedPotentialReconciliation(const QList<Terminal *> &terminals)
{
	QSet<Conductor *> potentials;
	QSet<Terminal *> excluded;
	for (Terminal *t : terminals) {
		if (excluded.contains(t)) continue;
		if (!t->conductors().isEmpty()) {
			Conductor *c = t->conductors().first();
			potentials.insert(c);
			for (Conductor *rc : c->relatedPotentialConductors(false)) {
				if (terminals.contains(rc->terminal1)) excluded.insert(rc->terminal1);
				else if (terminals.contains(rc->terminal2)) excluded.insert(rc->terminal2);
			}
		} else if ((t->parentElement()->linkType() & Element::AllReport)
				   && !t->parentElement()->isFree()) {
			const QList<Element *> linked = t->parentElement()->linkedElements();
			if (!linked.isEmpty() && !linked.first()->conductors().isEmpty())
				potentials.insert(linked.first()->conductors().first());
		}
		if (potentials.size() >= 2) return true;
	}
	return false;
}

/// Reject any op argument we did not ask for, so a typo or an unsupported
/// argument fails loudly instead of being silently ignored (the same contract
/// as the "as_group" rejection in the rotate op).
/// @return true if an unsupported key was found (and an error printed).
bool rejectUnsupportedArgs(const QJsonObject &op, const QString &kind,
						   const QStringList &supported)
{
	for (auto it = op.begin(); it != op.end(); ++it) {
		const QString key = it.key();
		if (key == "op" || supported.contains(key))
			continue;
		err << "test-ops: " << kind << " -- unsupported argument \""
			<< key << "\".\n";
		return true;
	}
	return false;
}

/// Resolve a "connect_rect" op: create conductor(s) between every terminal
/// found inside the given rectangle. Calls ConductorCreator::create()
/// directly (utils/conductorcreator.h) rather than reimplementing the
/// hub-and-spoke conductor layout -- it is the same class QET's own
/// rubber-band flood-connect tool uses, and the simple two-point "click a
/// terminal, drag, click another terminal" wire draw is just this with
/// exactly 2 terminals found (one conductor created between them).
///
/// Terminal discovery is duplicated here (not left to ConductorCreator::
/// create()) so wouldNeedPotentialReconciliation() can inspect the list
/// first and refuse before construction -- see that function's comment for
/// why the modal-dialog risk it guards is common, not an edge case.
/// Returns false (nothing done, caller should report an error) when the
/// rectangle contains fewer than 2 terminals or would trigger that dialog.
bool applyConnectRect(Diagram *diagram, const QJsonObject &rectObj)
{
	const QRectF rect(
		rectObj.value("x").toDouble(), rectObj.value("y").toDouble(),
		rectObj.value("w").toDouble(), rectObj.value("h").toDouble()
	);
	const QPolygonF polygon(rect);

	QList<Terminal *> t_list;
	for (QGraphicsItem *item : diagram->items(polygon))
		if (item->type() == Terminal::Type)
			t_list.append(qgraphicsitem_cast<Terminal *>(item));

	if (t_list.size() <= 1) {
		err << "test-ops: connect_rect -- fewer than 2 terminals in "
			<< rect.x() << "," << rect.y() << " " << rect.width() << "x"
			<< rect.height() << ", nothing to connect.\n";
		return false;
	}
	if (wouldNeedPotentialReconciliation(t_list)) {
		err << "test-ops: connect_rect -- rectangle spans terminals on 2+ "
			   "existing potentials with different properties; QET would "
			   "show a modal dialog to reconcile them, which hangs "
			   "headless. Refusing rather than hanging.\n";
		return false;
	}

	const int before = diagram->conductors().size();
	ConductorCreator::create(diagram, polygon);
	const int after = diagram->conductors().size();
	out << "test-ops: connect_rect -- " << (after - before) << " conductor(s) created in "
		<< rect.x() << "," << rect.y() << " " << rect.width() << "x"
		<< rect.height() << "\n";
	return true;
}

/// Read a numeric op argument into @p out. @return false (and print an error)
/// if the key is present but not a number; true if absent (leaving @p out
/// untouched, so callers can default it) or a valid number.
bool opNumber(const QJsonObject &op, const QString &key, qreal *out)
{
	if (!op.contains(key))
		return true;
	const QJsonValue value = op.value(key);
	if (value.isDouble()) {
		*out = value.toDouble();
		return true;
	}
	err << "test-ops: \"" << key << "\" must be a number.\n";
	return false;
}

/// Move the diagram's current selection by @p movement, mirroring the GUI drag:
/// apply the translation first, then push MoveGraphicsItemCommand so undo/redo
/// stay consistent. The command's first redo() is deliberately a no-op that
/// only records the animation -- it assumes the caller already moved the items
/// (the GUI mouse handler does the same), so without the explicit move here the
/// op would silently do nothing.
void applyMove(Diagram *diagram, const QPointF &movement)
{
	DiagramContent content(diagram);
	content.removeNonMovableItems();

	const auto movable = content.items(DiagramContent::Elements
									   | DiagramContent::TextFields
									   | DiagramContent::Images
									   | DiagramContent::Shapes
									   | DiagramContent::TextGroup
									   | DiagramContent::ElementTextFields
									   | DiagramContent::Tables
									   | DiagramContent::TerminalStrip);
	const auto all_items = content.items();
	for (QGraphicsItem *qgi : movable) {
		// An item whose parent is itself selected moves with its parent;
		// moving it again would double-count.
		if (const QGraphicsItem *parent = qgi->parentItem()) {
			if (all_items.contains(const_cast<QGraphicsItem *>(parent)))
				continue;
		}
		qgi->setPos(qgi->pos() + movement);
	}

	for (Conductor *conductor : content.m_conductors_to_move) {
		conductor->updatePath();
		if (conductor->textItem()->wasMovedByUser())
			conductor->textItem()->setPos(conductor->textItem()->pos() + movement);
	}
	for (Conductor *conductor : content.m_conductors_to_update)
		conductor->updatePath();

	diagram->undoStack().push(new MoveGraphicsItemCommand(diagram, content, movement));
}

/// Rotate every conductor text in @p diagram by @p angle. RotateTextsCommand
/// only touches *selected* texts, so select them all first -- a bare
/// {"op":"rotate_texts"} with no prior select op must still rotate the whole
/// folio's conductor labels.
void applyRotateTexts(Diagram *diagram, qreal angle)
{
	for (Conductor *conductor : diagram->conductors()) {
		if (ConductorTextItem *text = conductor->textItem())
			text->setSelected(true);
	}
	diagram->undoStack().push(new RotateTextsCommand(diagram, angle));
}

/// Headless, scripted editing for automated regression testing. See
/// cli_export.h for the op vocabulary and the JSON summary this prints.
int applyTestOps(QETProject &project, const QString &opsPath, const QString &output)
{
	QFile ops_file(opsPath);
	if (!ops_file.open(QIODevice::ReadOnly)) {
		err << "Cannot open ops file: " << opsPath << "\n";
		return 2;
	}
	QJsonParseError parse_error;
	const QJsonDocument ops_doc = QJsonDocument::fromJson(ops_file.readAll(), &parse_error);
	ops_file.close();
	if (parse_error.error != QJsonParseError::NoError || !ops_doc.isArray()) {
		err << "Malformed ops file (expected a JSON array): "
			<< parse_error.errorString() << "\n";
		return 2;
	}

	if (project.diagrams().isEmpty()) {
		err << "test-ops: project has no diagrams.\n";
		return 1;
	}
	Diagram *diagram = project.diagrams().first();

	int applied = 0;
	for (const QJsonValue &v : ops_doc.array()) {
		if (!v.isObject()) {
			err << "test-ops: skipping non-object op at index " << applied << "\n";
			continue;
		}
		const QJsonObject op = v.toObject();
		const QString kind = op.value("op").toString();

		if (kind == "set_diagram") {
			// Which folio subsequent ops target. project.diagrams() is
			// QETProject::m_diagrams_list -- the same ordered list
			// folioIndex() computes positions from (0-based: folioIndex()'s
			// own doc comment says "returns 0 for the first diagram, not
			// 1"), maintained directly by insert/remove, not subject to the
			// QGraphicsScene::items()/toXml() traversal-order
			// non-determinism that affects element and conductor ordering
			// (FINDINGS.md F002-F004). Verified this is the right list to
			// index, not assumed.
			if (!op.contains("index")) {
				err << "test-ops: set_diagram -- requires \"index\".\n";
				return 2;
			}
			const int idx = op.value("index").toInt(-1);
			const QList<Diagram *> all_diagrams = project.diagrams();
			if (idx < 0 || idx >= all_diagrams.size()) {
				err << "test-ops: set_diagram -- index " << idx
					<< " out of range (project has " << all_diagrams.size()
					<< " folio(s)).\n";
				return 1;
			}
			diagram = all_diagrams.at(idx);
			diagram->clearSelection();
		}
		else if (kind == "select") {
			applySelect(diagram, op.value("uuids").toArray());
		}
		else if (kind == "select_rect") {
			if (!op.contains("x") || !op.contains("y")
				|| !op.contains("w") || !op.contains("h")) {
				err << "test-ops: select_rect -- requires x, y, w, h.\n";
				return 2;
			}
			applySelectRect(diagram, op);
		}
		else if (kind == "connect_rect") {
			if (!op.contains("x") || !op.contains("y")
				|| !op.contains("w") || !op.contains("h")) {
				err << "test-ops: connect_rect -- requires x, y, w, h.\n";
				return 2;
			}
			if (!applyConnectRect(diagram, op)) {
				return 1;
			}
		}
		else if (kind == "link") {
			if (!applyLink(diagram, op.value("uuids").toArray())) {
				return 1;
			}
		}
		else if (kind == "paste") {
			if (!op.contains("x") || !op.contains("y")) {
				err << "test-ops: paste -- requires \"x\" and \"y\".\n";
				return 2;
			}
			if (!applyPaste(diagram, op.value("x").toDouble(), op.value("y").toDouble())) {
				return 1;
			}
		}
		else if (kind == "move") {
			if (!op.contains("dx") || !op.contains("dy")) {
				err << "test-ops: move -- requires \"dx\" and \"dy\".\n";
				return 2;
			}
			if (!applyMove(diagram, op.value("dx").toDouble(), op.value("dy").toDouble())) {
				err << "test-ops: move -- nothing selected/movable, no-op.\n";
				return 1;
			}
		}
		else if (kind == "delete") {
			DiagramContent dc(diagram);
			if (DeleteQGraphicsItemCommand::hasNonDeletableTerminal(dc)) {
				err << "test-ops: delete -- selection has a non-deletable "
					   "(bridged/multi-level) terminal, refusing.\n";
				return 1;
			}
			diagram->undoStack().push(new DeleteQGraphicsItemCommand(diagram, dc));
		}
		else if (kind == "rotate") {
			// NOTE: master's RotateSelectionCommand does not yet have the
			// "rotate as a whole group" mode -- that is PR #660, not
			// merged at the time this was written. An "as_group" op
			// argument is deliberately not accepted here rather than
			// silently ignored, so a caller relying on it fails loudly
			// instead of getting single-item rotation without noticing.
			if (op.contains("as_group")) {
				err << "test-ops: rotate -- \"as_group\" is not supported on this "
					   "build (needs PR #660, not merged yet).\n";
				return 2;
			}
			const qreal angle = op.contains("angle") ? op.value("angle").toDouble() : 90.0;
			auto *c = new RotateSelectionCommand(diagram, angle, nullptr);
			if (c->isValid()) {
				diagram->undoStack().push(c);
			} else {
				err << "test-ops: rotate -- nothing selected, no-op.\n";
				delete c;
			}
		}
		else if (kind == "select_all") {
			if (rejectUnsupportedArgs(op, "select_all", {}))
				return 2;
			diagram->selectAll();
		}
		else if (kind == "diagram") {
			if (rejectUnsupportedArgs(op, "diagram", {"index"}))
				return 2;
			const double index_value = op.value("index").toDouble();
			if (!op.contains("index") || !op.value("index").isDouble()
				|| index_value != int(index_value)) {
				err << "test-ops: diagram -- \"index\" is required and must be an integer.\n";
				return 2;
			}
			const int idx = int(index_value);
			if (idx < 0 || idx >= project.diagrams().size()) {
				err << "test-ops: diagram -- index " << idx << " out of range (project has "
					<< project.diagrams().size() << " diagram(s)).\n";
				return 2;
			}
			diagram = project.diagrams().at(idx);
		}
		else if (kind == "set_property") {
			if (rejectUnsupportedArgs(op, "set_property", {"uuid", "key", "value"}))
				return 2;
			const QString uuid = op.value("uuid").toString();
			const QString key = op.value("key").toString();
			const QString value = op.value("value").toString();
			if (uuid.isEmpty() || key.isEmpty()) {
				err << "test-ops: set_property -- \"uuid\" and \"key\" are required.\n";
				return 2;
			}
			Element *target = nullptr;
			for (Element *e : diagram->elements()) {
				if (e->uuid() == QUuid(uuid)) {
					target = e;
					break;
				}
			}
			if (!target) {
				err << "test-ops: set_property -- uuid not found in diagram: " << uuid << "\n";
				return 2;
			}
			DiagramContext old_info = target->elementInformations();
			DiagramContext new_info = old_info;
			if (!new_info.addValue(key, value)) {
				err << "test-ops: set_property -- key \"" << key << "\" is not acceptable.\n";
				return 2;
			}
			diagram->undoStack().push(
				new ChangeElementInformationCommand(target, old_info, new_info));
		}
		else if (kind == "rotate_texts") {
			if (rejectUnsupportedArgs(op, "rotate_texts", {"angle"}))
				return 2;
			qreal angle = 90.0;
			if (!opNumber(op, "angle", &angle))
				return 2;
			applyRotateTexts(diagram, angle);
		}
		else if (kind == "undo") {
			diagram->undoStack().undo();
		}
		else if (kind == "redo") {
			diagram->undoStack().redo();
		}
		else {
			err << "test-ops: unknown op \"" << kind << "\" at index " << applied << "\n";
			return 2;
		}
		++applied;
	}

	const int save_result = resaveProject(project, output);
	if (save_result != 0) return save_result;

	int element_count = -1, element_info_count = -1;
	int conductor_count = -1, conductor_distinct = -1, terminal_count = -1;
	QSqlQuery ec = project.dataBase()->newQuery(QStringLiteral("SELECT COUNT(*) FROM element"));
	if (ec.next()) element_count = ec.value(0).toInt();
	QSqlQuery eic = project.dataBase()->newQuery(QStringLiteral("SELECT COUNT(*) FROM element_info"));
	if (eic.next()) element_info_count = eic.value(0).toInt();
	QSqlQuery cc = project.dataBase()->newQuery(QStringLiteral("SELECT COUNT(*) FROM conductor"));
	if (cc.next()) conductor_count = cc.value(0).toInt();
	QSqlQuery cd = project.dataBase()->newQuery(QStringLiteral("SELECT COUNT(DISTINCT uuid) FROM conductor"));
	if (cd.next()) conductor_distinct = cd.value(0).toInt();
	QSqlQuery tc = project.dataBase()->newQuery(QStringLiteral("SELECT COUNT(*) FROM terminal"));
	if (tc.next()) terminal_count = tc.value(0).toInt();

	QJsonObject summary;
	summary["ops_applied"] = applied;
	summary["element_count"] = element_count;
	summary["element_info_count"] = element_info_count;
	summary["conductor_count"] = conductor_count;
	summary["conductor_distinct"] = conductor_distinct;
	summary["terminal_count"] = terminal_count;
	out << QJsonDocument(summary).toJson(QJsonDocument::Compact) << "\n";

	return 0;
}

/// Stamp title-block fields onto every folio (and the project default), then
/// save.  Each assignment is "key=value".  Standard keys map to the documented
/// title-block fields; "date=today" uses the current date; any other key is
/// stored as a custom title-block field.  Aimed at CI/revision workflows
/// (e.g. set revision + date before exporting a new revision).
int setTitleBlock(QETProject &project, const QString &output,
				  const QStringList &assignments)
{
	if (assignments.isEmpty()) {
		err << "No field assignments given (expected key=value).\n";
		return 2;
	}

	// Parse "key=value" assignments up front so a bad one fails before writing.
	QList<QPair<QString, QString>> fields;
	for (const QString &a : assignments) {
		const int eq = a.indexOf('=');
		if (eq <= 0) {
			err << "Bad assignment '" << a << "' (expected key=value).\n";
			return 2;
		}
		const QString key = a.left(eq);
		const QString val = a.mid(eq + 1);
		if (key.compare("date", Qt::CaseInsensitive) == 0
			&& val.compare("today", Qt::CaseInsensitive) != 0
			&& !QDate::fromString(val, Qt::ISODate).isValid()) {
			err << "Bad date '" << val << "' (expected YYYY-MM-DD or 'today').\n";
			return 2;
		}
		fields << qMakePair(key, val);
	}

	auto apply = [&](TitleBlockProperties &p) {
		for (const auto &f : fields) {
			const QString k = f.first.toLower();
			const QString &v = f.second;
			if      (k == "title")    p.title    = v;
			else if (k == "author")   p.author   = v;
			else if (k == "filename") p.filename = v;
			else if (k == "plant")    p.plant    = v;
			else if (k == "location") p.locmach  = v;
			else if (k == "revision") p.indexrev = v;
			else if (k == "version")  p.version  = v;
			else if (k == "date") {
				p.date = (v.compare("today", Qt::CaseInsensitive) == 0)
						 ? QDate::currentDate()
						 : QDate::fromString(v, Qt::ISODate);
				// An explicit date is only honoured when the folio is in
				// "use the date value" mode (not "now"/"null").
				p.useDate = TitleBlockProperties::UseDateValue;
			}
			else // unknown key -> custom title-block field
				p.context.addValue(f.first, v);
		}
	};

	// Project default (the template applied to new folios).
	TitleBlockProperties def = project.defaultTitleBlockProperties();
	apply(def);
	project.setDefaultTitleBlockProperties(def);

	// Every existing folio's own title block.
	int folios = 0;
	const QList<Diagram *> diagrams = project.diagrams();
	for (Diagram *diagram : diagrams) {
		TitleBlockProperties p =
			diagram->border_and_titleblock.exportTitleBlock();
		apply(p);
		diagram->border_and_titleblock.importTitleBlock(p);
		++folios;
	}

	const QDomDocument doc = project.toXml();
	QFile file(output);
	if (!file.open(QIODevice::WriteOnly | QIODevice::Text)) {
		err << "Cannot open '" << output << "' for writing.\n";
		return 1;
	}
	QTextStream fout(&file);
	fout << doc.toString(4);
	file.close();
	out << "Stamped " << fields.size() << " field(s) on "
		<< folios << " folio(s) -> " << output << "\n";
	return 0;
}

} // anonymous namespace

namespace CLIExport {

bool isExportRequest(const QStringList &args)
{
	for (const QString &a : args)
		if (exportFlags().contains(a))
			return true;
	return false;
}

int run(const QStringList &args)
{
	QString flag;
	QStringList rest;
	for (int i = 0; i < args.size(); ++i) {
		if (exportFlags().contains(args.at(i))) {
			flag = args.at(i);
			for (int j = i + 1; j < args.size(); ++j)
				rest << args.at(j);
			break;
		}
	}
	const QString format = exportFlags().value(flag);

	// --check-elements operates on an element file/directory, not a project.
	if (format == "check") {
		if (rest.isEmpty()) {
			err << "Usage: qelectrotech --check-elements "
				   "<element.elmt | directory>\n";
			return 2;
		}
		return checkElements(rest.at(0));
	}

	const QString input = rest.value(0);
	if (input.isEmpty()) {
		err << "Usage: qelectrotech " << flag << " <project.qet> <output>\n";
		return 2;
	}
	if (!QFileInfo::exists(input)) {
		err << "Project not found: " << input << "\n";
		return 2;
	}

	QETProject project(input);
	if (project.state() != QETProject::Ok) {
		err << "Failed to open project: " << input
			<< " (state " << project.state() << ")\n";
		return 1;
	}

	// --info writes JSON to stdout, or to an optional output file.
	if (format == "info")
		return exportInfo(project, rest.value(1));

	// --test-ops takes three positional args (project, ops file, output)
	// rather than the (project, output) shape everything else below
	// shares, so it must be handled before the generic `output` slot.
	if (format == "testops") {
		const QString ops_path = rest.value(1);
		const QString testops_output = rest.value(2);
		if (ops_path.isEmpty() || testops_output.isEmpty()) {
			err << "Usage: qelectrotech --test-ops <project.qet> <ops.json> <output.qet>\n";
			return 2;
		}
		return applyTestOps(project, ops_path, testops_output);
	}

	const QString output = rest.value(1);
	if (output.isEmpty()) {
		err << "Usage: qelectrotech " << flag
			<< " <project.qet> <output>\n";
		return 2;
	}
	if (format == "pdf")
		return exportPdf(project, output);
	if (format == "cables" || format == "wires")
		return exportCsv(project, format, output);
	if (format == "bom")
		return exportBom(project, output);
	if (format == "nets")
		return exportNets(project, output);
	if (format == "links")
		return exportLinks(project, output);
	if (format == "resave")
		return resaveProject(project, output);
	if (format == "settb")
		return setTitleBlock(project, output, rest.mid(2));
	return exportImages(project, format, output);
}

} // namespace CLIExport
