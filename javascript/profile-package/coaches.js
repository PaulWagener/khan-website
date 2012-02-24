var Coaches = {};

Coaches.CoachView = Backbone.View.extend({
    className: "coach-row",
    template_: null,

    initialize: function() {
        this.template_ = Templates.get("profile.coach");
    },

    render: function() {
        var context = this.model.toJSON();

        $(this.el).html(this.template_(context));

        return this;
    }
});

Coaches.CoachList = Backbone.Collection.extend({
    model: ProfileModel
});

Coaches.CoachListView = Backbone.View.extend({
    initialize: function() {
        this.coachViews_ = [];

        this.collection.each(this.add, this);

        this.collection.bind("add", this.add, this);
        this.collection.bind("remove", this.remove, this);

    },

    add: function(model) {
        var coachView = new Coaches.CoachView({
            model: model
        });
        this.coachViews_.push(coachView);
        this.render();
    },

    remove: function(model) {
        var viewToRemove = _.find(this.coachViews_, function(view) {
                return view.model === model;
            });

        if (viewToRemove) {
            this.coachViews_ = _.without(this.coachViews_, viewToRemove);
            this.render();
        }
    },

    render: function() {
        $(this.el).empty();

        if (this.collection.isEmpty()) {
            $(this.el).append("You have no coaches. Why not add a coach?")
        } else {
            _.each(this.coachViews_, function(view) {
                $(this.el).append(view.render().el);
            }, this);
        }

        return this;
    }
});
