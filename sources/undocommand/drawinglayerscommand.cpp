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
#include "drawinglayerscommand.h"

#include "../dataBase/projectdatabase.h"
#include "../qetproject.h"

#include <QGraphicsObject>
#include <QObject>

DrawingLayersCommand::DrawingLayersCommand(QETProject *project, const DrawingLayers::Set &layers,
										   const QHash<QGraphicsObject *, QString> &item_layers,
										   QUndoCommand *parent) :
	QUndoCommand(QObject::tr("Change the layers"), parent),
	m_project(project),
	m_new_layers(layers)
{
	if (project) m_old_layers = project->drawingLayers();
	for (auto it = item_layers.constBegin() ; it != item_layers.constEnd() ; ++it) {
		m_old_items.append({it.key(), DrawingLayers::layerOf(it.key())});
		m_new_items.append({it.key(), it.value()});
	}
}

void DrawingLayersCommand::apply(const DrawingLayers::Set &layers,
								 const QList<QPair<QPointer<QGraphicsObject>, QString>> &items)
{
	if (!m_project) return;
	for (const auto &item : items) {
		if (!item.first) continue;
		DrawingLayers::setLayerOf(item.first, item.second);
		m_project->dataBase()->drawingItemTouched(item.first);
	}
	m_project->setDrawingLayers(layers);
	m_project->setModified(true);
}

void DrawingLayersCommand::undo() {apply(m_old_layers, m_old_items);}
void DrawingLayersCommand::redo() {apply(m_new_layers, m_new_items);}
