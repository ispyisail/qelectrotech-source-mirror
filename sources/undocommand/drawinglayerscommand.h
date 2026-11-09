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
#ifndef DRAWINGLAYERSCOMMAND_H
#define DRAWINGLAYERSCOMMAND_H

#include "../drawinglayers/drawinglayers.h"

#include <QHash>
#include <QPointer>
#include <QUndoCommand>

class QETProject;
class QGraphicsObject;

/**
	@brief The DrawingLayersCommand class
	Changes a project's layers and groups and, together, which layer some
	items are on: putting a selection on a layer, removing or renaming one.
*/
class DrawingLayersCommand : public QUndoCommand
{
	public:
		DrawingLayersCommand(QETProject *project, const DrawingLayers::Set &layers,
							 const QHash<QGraphicsObject *, QString> &item_layers = {},
							 QUndoCommand *parent = nullptr);

		void undo() override;
		void redo() override;

	private:
		void apply(const DrawingLayers::Set &layers, const QList<QPair<QPointer<QGraphicsObject>, QString>> &items);

		QPointer<QETProject> m_project;
		DrawingLayers::Set m_old_layers;
		DrawingLayers::Set m_new_layers;
		QList<QPair<QPointer<QGraphicsObject>, QString>> m_old_items;
		QList<QPair<QPointer<QGraphicsObject>, QString>> m_new_items;
};

#endif // DRAWINGLAYERSCOMMAND_H
