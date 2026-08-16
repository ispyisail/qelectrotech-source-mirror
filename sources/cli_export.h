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
#ifndef CLI_EXPORT_H
#define CLI_EXPORT_H

#include <QStringList>

/**
	@brief Headless command-line export.

	Implements the long-requested batch/headless export
	(qelectrotech.org bugtracker #171, GitHub #309): render a project's
	diagrams to files without opening the GUI.

	Detected and handled in main() before the GUI is created.
*/
namespace CLIExport {

	/**
		@brief True if @p args request a CLI export
		(i.e. contain one of the export options).
	*/
	bool isExportRequest(const QStringList &args);

	/**
		@brief Run the CLI export described by @p args.
		@return process exit code (0 on success).

		Usage:
		  qelectrotech --export-pdf     <project.qet> <output.pdf>
		  qelectrotech --export-png     <project.qet> <output_dir>
		  qelectrotech --export-svg     <project.qet> <output_dir>
		  qelectrotech --export-cables  <project.qet> <output.csv>
		  qelectrotech --export-wires   <project.qet> <output.csv>
		  qelectrotech --export-bom     <project.qet> <output.csv>
		  qelectrotech --export-nets    <project.qet> <output.json>
		  qelectrotech --export-links   <project.qet> <output.csv>
		  qelectrotech --info           <project.qet> [output.json]
		  qelectrotech --check-elements <element.elmt | directory>
		  qelectrotech --resave         <project.qet> <output.qet>
		  qelectrotech --set-titleblock <project.qet> <output.qet> key=value...
		  qelectrotech --test-ops       <project.qet> <ops.json> <output.qet>

		PDF: one multi-page document (one diagram per page).
		PNG/SVG: one file per diagram, named <output_dir>/<NN>_<title>.<ext>.
		cables: wiring list (one row per conductor) as CSV.
		wires: list of distinct wire numbers as CSV.
		bom: bill of materials (one row per element) as CSV.
		nets: electrical nets (connected-terminal groups) as JSON.
		links: element cross-references (coil/contact) as CSV, with
		       unresolved links flagged.
		info: structural project summary as JSON (stdout, or a file) —
		      per-page element / conductor counts and unconnected terminals.
		check-elements: validate .elmt file(s) against the element schema.
		resave: load and rewrite the project XML (round-trip integrity).
		set-titleblock: stamp title-block fields onto every folio, then save.
		      Keys: title, author, date (or date=today), plant, location,
		      revision, version, filename; any other key becomes a custom
		      field.  E.g. --set-titleblock in.qet out.qet revision=B date=today
		test-ops: headless, scripted editing for automated regression
		      testing (not an end-user feature). Applies a JSON array of
		      operations to a diagram's selection state (the first diagram
		      by default -- see set_diagram below to target another one),
		      in the same code path the GUI uses (DeleteQGraphicsItemCommand,
		      RotateSelectionCommand, MoveGraphicsItemCommand,
		      RotateTextsCommand, ChangeElementInformationCommand,
		      QUndoStack::undo/redo), then saves.
		      Ops (each a JSON object with an "op" key):
		        {"op": "set_diagram", "index": 0}
		            Switches which diagram subsequent ops target, addressed
		            by the same 0-based position QETProject::folioIndex()
		            reports (project.diagrams().at(index)) -- so a folio's
		            index here is the same number that identifies it
		            elsewhere in QET, not an arbitrary list slot. Clears
		            the new diagram's selection. "index" is required and
		            must be in range, or the op fails (exit 2 / 1).
		        {"op": "select", "uuids": ["{...}", ...]}
		            Clears the diagram's selection, then selects every
		            element whose uuid is listed. Unknown uuids are
		            reported on stderr and otherwise ignored.
		        {"op": "select_rect", "x": 0, "y": 0, "w": 100, "h": 100}
		            Clears the diagram's selection, then selects every
		            element whose scene bounding rect intersects the given
		            rectangle -- a headless rubber-band drag. Matches QET's
		            real default (DiagramView sets RubberBandDrag and never
		            overrides the selection mode, so Qt's own default,
		            Qt::IntersectsItemShape, applies); approximated here
		            with bounding-rect intersection rather than exact
		            painted shape, which agrees in the overwhelming
		            majority of cases for QET's mostly-rectangular symbol
		            bodies. All four keys are required.
		        {"op": "connect_rect", "x": 0, "y": 0, "w": 100, "h": 100}
		            Creates conductor(s) between every terminal found inside
		            the given rectangle (ConductorCreator::create(),
		            utils/conductorcreator.h) -- the same class QET's
		            rubber-band flood-connect tool uses. Exactly 2 terminals
		            in the rectangle -> 1 new conductor (the simple wire-draw
		            case); 3+ -> a hub-and-spoke potential, same as the GUI
		            flood tool; 0 or 1 -> no-op. All four keys are required.
		            If the rectangle spans terminals on 2+ existing
		            potentials with different properties, QET would show a
		            modal properties-reconciliation dialog to resolve them,
		            which hangs under headless/offscreen operation -- measured
		            on real data to be common for any rectangle over a
		            populated area of a real diagram, not a rare edge case, so
		            this is detected up front (mirroring ConductorCreator's
		            own, private, trigger check) and the op fails (exit 1)
		            instead of hanging.
		        {"op": "link", "uuids": ["{primary}", "{target}", ...]}
		            Links uuids[0] (the element the link is edited FOR, e.g. a
		            master or a folio-report element) to every other element
		            in the list, via LinkElementCommand -- the same class the
		            GUI's cross-reference linking uses. At least 2 uuids
		            required. Every candidate is checked with
		            LinkElementCommand::isLinkable() first; any non-linkable
		            candidate fails the whole op (exit 1), rather than
		            silently linking a smaller subset. Refuses (exit 1) rather
		            than hanging if linking two folio-report elements would
		            trigger QET's modal properties-reconciliation dialog
		            (differing conductor text/function/tension across the
		            merged potential) -- always run test-ops with a timeout
		            regardless.
		        {"op": "paste", "x": 100, "y": 100}
		            Duplicates the current selection, positioning the pasted
		            copy's bounding-rect top-left at (x, y) -- the same
		            "position" semantics Diagram::fromXml() itself documents.
		            Bypasses the system clipboard DiagramView::copy()/paste()
		            use (fragile/unavailable headless) but reuses their exact
		            serialize (toXml) / import (fromXml) calls otherwise, so
		            it exercises the real paste code path. Fails (exit 1) if
		            the diagram is read-only or nothing is selected. Both
		            keys are required.
		        {"op": "move", "dx": 10, "dy": 0}
		            Translates the current selection by (dx, dy), using the
		            same ElementsMover class (elementsmover.h) the GUI's
		            mouse-drag move uses, so attached conductors are
		            recalculated exactly as they would be after a real drag,
		            and a single-element move still triggers the project's
		            auto-conductor connection when enabled. Both keys are
		            required.
		        {"op": "select_all"}
		            Selects every item in the current diagram.
		        {"op": "delete"}
		            Deletes the current selection (same command the GUI's
		            "Delete" action pushes).
		        {"op": "rotate", "angle": 90}
		            Rotates the current selection in place ("angle"
		            defaults to 90). Rotating as a single rigid group
		            (the GUI's "Pivoter le groupe") is not available
		            here yet -- it needs PR #660, not merged as of this
		            writing; an "as_group" key is rejected rather than
		            silently ignored.
		        {"op": "move", "dx": 0, "dy": 0}
		            Translates the current selection by (dx, dy).
		        {"op": "diagram", "index": 0}
		            Switches the target diagram for every subsequent op
		            (0-based; an out-of-range index is an error).
		        {"op": "set_property", "uuid": "{...}", "key": "...", "value": "..."}
		            Sets one element-information key on the element with
		            the given uuid (DiagramContext keys: "label",
		            "designation", "manufacturer", ...).
		        {"op": "rotate_texts", "angle": 90}
		            Rotates every conductor text in the current diagram
		            (conductor texts are selected first, since
		            RotateTextsCommand only acts on the selection).
		        {"op": "undo"} / {"op": "redo"}
		            One step on the current diagram's QUndoStack.
		      On completion, prints a one-line JSON summary to stdout:
		      {"ops_applied": N, "element_count": N, "element_info_count": N}
		      -- the last two are row counts from the in-memory project
		      database (SELECT COUNT(*) FROM element / element_info), the
		      same table PR #664 found leaking orphan rows on delete+undo.
		      A mismatch between them is exactly that bug class,
		      independent of which specific operation caused it.
	*/
	int run(const QStringList &args);

}

#endif // CLI_EXPORT_H
