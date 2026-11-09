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
#include "drawinglayers.h"

#include "../diagram.h"
#include "../qetgraphicsitem/diagramimageitem.h"
#include "../qetgraphicsitem/independenttextitem.h"
#include "../qetgraphicsitem/qetshapeitem.h"
#include "../shownkinds.h"

#include <QGraphicsItem>

namespace DrawingLayers
{
	namespace
	{
		const int LayerKey = 0x4c4159;  // "LAY"
	}

	bool Set::contains(const QString &name) const
	{
		for (const Layer &layer : layers)
			if (layer.name == name) return true;
		return false;
	}

	/**
		@return whether what is on layer @p name shows; a layer the project
		does not know (a pasted item's) is on
	*/
	bool Set::isVisible(const QString &name) const
	{
		for (const Layer &layer : layers)
			if (layer.name == name) return layer.visible;
		return true;
	}

	QStringList Set::names() const
	{
		QStringList list;
		for (const Layer &layer : layers) list << layer.name;
		return list;
	}

	/**
		@return this set with the layers of @p group on and the others off
	*/
	Set Set::showing(const Group &group) const
	{
		Set set = *this;
		for (Layer &layer : set.layers) layer.visible = group.layers.contains(layer.name);
		return set;
	}

	QDomElement Set::toXml(QDomDocument &document) const
	{
		QDomElement root = document.createElement(QStringLiteral("layers"));
		for (const Layer &layer : layers) {
			QDomElement element = document.createElement(QStringLiteral("layer"));
			element.setAttribute(QStringLiteral("name"), layer.name);
			element.setAttribute(QStringLiteral("visible"), layer.visible ? QStringLiteral("true") : QStringLiteral("false"));
			root.appendChild(element);
		}
		for (const Group &group : groups) {
			QDomElement element = document.createElement(QStringLiteral("layer_group"));
			element.setAttribute(QStringLiteral("name"), group.name);
			for (const QString &name : group.layers) {
				QDomElement member = document.createElement(QStringLiteral("member"));
				member.setAttribute(QStringLiteral("name"), name);
				element.appendChild(member);
			}
			root.appendChild(element);
		}
		return root;
	}

	Set Set::fromXml(const QDomElement &element)
	{
		Set set;
		for (QDomElement e = element.firstChildElement(QStringLiteral("layer")) ; !e.isNull()
			 ; e = e.nextSiblingElement(QStringLiteral("layer"))) {
			const QString name = e.attribute(QStringLiteral("name")).trimmed();
			if (name.isEmpty() || set.contains(name)) continue;
			set.layers.append({name, e.attribute(QStringLiteral("visible")) != QLatin1String("false")});
		}
		for (QDomElement e = element.firstChildElement(QStringLiteral("layer_group")) ; !e.isNull()
			 ; e = e.nextSiblingElement(QStringLiteral("layer_group"))) {
			Group group;
			group.name = e.attribute(QStringLiteral("name")).trimmed();
			for (QDomElement m = e.firstChildElement(QStringLiteral("member")) ; !m.isNull()
				 ; m = m.nextSiblingElement(QStringLiteral("member")))
				group.layers << m.attribute(QStringLiteral("name"));
			if (!group.name.isEmpty()) set.groups << group;
		}
		return set;
	}

	QString layerOf(const QGraphicsItem *item)
	{
		return item ? item->data(LayerKey).toString() : QString();
	}

	void setLayerOf(QGraphicsItem *item, const QString &layer)
	{
		if (!item) return;
		item->setData(LayerKey, layer.isEmpty() ? QVariant() : QVariant(layer));
	}

	void writeAttribute(const QGraphicsItem *item, QDomElement &element)
	{
		const QString layer = layerOf(item);
		if (!layer.isEmpty()) element.setAttribute(QStringLiteral("layer"), layer);
	}

	void readAttribute(QGraphicsItem *item, const QDomElement &element)
	{
		setLayerOf(item, element.attribute(QStringLiteral("layer")));
	}

	bool canBeOnLayer(const QGraphicsItem *item)
	{
		return qgraphicsitem_cast<const QetShapeItem *>(item)
				|| qgraphicsitem_cast<const IndependentTextItem *>(item)
				|| qgraphicsitem_cast<const DiagramImageItem *>(item);
	}

	/**
		@return whether @p item is hidden by its layer, for code walking the
		items itself (DXF export)
	*/
	bool isHidden(const QGraphicsItem *item)
	{
		return item && !layerOf(item).isEmpty() && !item->isVisible();
	}

	/**
		@brief apply
		Shows or hides @p item as its layer says; through ShownKinds, so
		that View > Show and the layers each only veto.
	*/
	void apply(QGraphicsItem *item, const Set &set)
	{
		if (!canBeOnLayer(item)) return;
		ShownKinds::setVisible(item, set.isVisible(layerOf(item)));
	}

	void applyTo(Diagram *folio, const Set &set)
	{
		if (!folio) return;
		for (QGraphicsItem *item : folio->items())
			apply(item, set);
	}
}
