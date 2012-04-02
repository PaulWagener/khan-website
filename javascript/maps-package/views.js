
// TODO: would be nice if this were part of a larger KnowledgeMap context
// instead of needing the KnowledgeMap naming prefix.
var KnowledgeMapViews = {};

/**
 * NodeRow is a base view class that can be used to render
 * a row in the knowledge map's left-hand drawer. It should
 * be extended by any type of Node, such as ExerciseRow and TopicRow.
 */
KnowledgeMapViews.NodeRow = Backbone.View.extend({

    initialize: function() {
        this.visible = false;
        this.nodeName = this.model.get("name");
        this.parent = this.options.parent;
    },

    events: {
        "click .skill-bar-title a": "onTitleClick",
        "click .pan-to": "onPanToClick"
    },

    inflate: function() {
        if (this.inflated)
            return;

        var template = this.getTemplate();
        var context = this.model.toJSON();

        context.disabled = this.model.get("invalidForGoal") || false;

        var newContent = $(template(context));
        var self = this;
        newContent.hover(
            function() {self.onBadgeMouseover(self.nodeName, newContent);},
            function() {self.onBadgeMouseout(self.nodeName, newContent);}
        );

        this.el.replaceWith(newContent);
        this.el = newContent;
        this.inflated = true;
        this.delegateEvents();
    },

    onTitleClick: function(evt) {
        // give the parent a chance to handle this exercise click. If it
        // doesn't, we'll just follow the anchor href
        return this.parent.nodeClickHandler(this.model, evt);
    },

    onBadgeMouseover: function(node_name, element) {
        this.parent.highlightNode(node_name, true);

        element.find(".pan-to").show();
    },

    onBadgeMouseout: function(node_name, element) {
        this.parent.highlightNode(node_name, false);

        element.find(".pan-to").hide();
    },

    onPanToClick: function() {
        this.parent.panToNode(this.nodeName);
        this.parent.highlightNode(this.nodeName, true);
    }

});

/**
 * ExerciseRow renders exercise-specific rows in the knowledge map's left-hand
 * drawer.
 */
KnowledgeMapViews.ExerciseRow = KnowledgeMapViews.NodeRow.extend({

    getTemplate: function() {
        // TODO: do these templates really need to be in "shared"?
        return Templates.get(this.options.admin ? "shared.knowledgemap-admin-exercise" : "shared.knowledgemap-exercise");
    },

    showGoalIcon: function(visible) {
        if (visible) {
            this.el.find(".exercise-goal-icon").show();
        }
        else {
            this.el.find(".exercise-goal-icon").hide();
        }
    }

});

/**
 * TopicRow renders topic-specific rows in the knowledge map's left-hand
 * drawer.
 */
KnowledgeMapViews.TopicRow = KnowledgeMapViews.NodeRow.extend({

    getTemplate: function() {
        return Templates.get("exercises.knowledgemap-topic");
    }

});

/**
 * NodeMarker renders nodes of any type on the knowledge map itself.
 */
KnowledgeMapViews.NodeMarker = Backbone.View.extend({

    events: {
        "click": "click",
        "mouseenter": "mouseenter",
        "mouseleave": "mouseout"
    },

    initialize: function(options) {
        this.nodeName = this.model.get("name");
        this.filtered = false;
        this.parent = this.options.parent;

        this.updateElement(this.el);
    },

    updateElement: function(el) {
        this.el = el;
        this.delegateEvents();
    },

    setFiltered: function(filtered, bounds) {
        if (filtered != this.filtered) {
            this.filtered = filtered;
        }

        var updateAppearance;
        if (bounds) {
            // only update appearance of nodes that are currently on screen
            var node = this.parent.dictNodes[this.nodeName];
            updateAppearance = bounds.contains(node.latLng);
        }
        else {
            updateAppearance = true;
        }

        // if we're in the window, update
        if (updateAppearance) {
            this.updateAppearance();
        }
    },

    updateAppearance: function() {

        // set class for css to apply styles
        if (this.filtered) {
            this.el.addClass("nodeLabelFiltered");
        } else {
            this.el.removeClass("nodeLabelFiltered");
        }

    },

    setHighlight: function(highlight) {
        if (highlight)
            this.el.addClass("nodeLabelHighlight");
        else
            this.el.removeClass("nodeLabelHighlight");
    },

    click: function(evt) {

        if (this.parent.fDragging) {
            // If the map is in the middle of being dragged/panned,
            // ignore clicks on nodes.
            evt.preventDefault();
            return;
        }

        if (!this.model.isClickableAtZoom(this.parent.map.getZoom())) {
            // If this node isn't clickable, make sure the default click event
            // of following the node's link doesn't happen.
            evt.preventDefault();
            return;
        }

        return this.parent.nodeClickHandler(this.model, evt);
    },

    mouseenter: function() {
        this.parent.highlightNode(this.nodeName, true);
    },

    mouseout: function() {
        this.parent.highlightNode(this.nodeName, false);
    }
},
{
    extendBounds: function(bounds, dlat, dlng) {
        dlat = dlat || KnowledgeMapGlobals.nodeSpacing.lat;
        dlng = dlat || KnowledgeMapGlobals.nodeSpacing.lng;

        var ne = bounds.getNorthEast();
        var nee = new google.maps.LatLng(ne.lat() + dlat, ne.lng() + dlng);

        var sw = bounds.getSouthWest();
        var swe = new google.maps.LatLng(sw.lat() - dlat, sw.lng() - dlng);

        return new google.maps.LatLngBounds(swe, nee);
    }

});
