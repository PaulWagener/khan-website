import string

from google.appengine.ext import db

import object_property
import models
from badges import Badge, BadgeCategory
from templatefilters import slugify

def sync_with_topic_version(version):
    """ Syncs state of all TopicExerciseBadges with the specified TopicVersion's topic tree.
    This'll add new badges for any new topics that have exercises, retire badges associated
    with topics that no longer contain exercises, and keep all constituent exercise names
    up-to-date.
    """

    # Get all topics with live exercises as direct children
    topics = models.Topic.get_exercise_topics(version)

    entities_to_put = []

    # Make sure there is a TopicExerciseBadgeType for every topic that contains exercises
    for topic in topics:

        badge_type = TopicExerciseBadgeType.get_or_insert_for_topic(topic)

        # If we didn't succeed in creation, bail hard so we can figure out what's going on
        if not badge_type:
            raise Exception("Failed to create TopicExerciseBadgeType for topic: %s" % topic.standalone_title)

        # Get all required exercise names for this topic
        exercise_names_required = [ex.name for ex in topic.children]

        # If the badge needs its required exercises updated or 
        # was previously retired, update it.
        if (badge_type.retired or 
                set(exercise_names_required) != set(badge_type.exercise_names_required)):

            badge_type.retired = False
            badge_type.exercise_names_required = exercise_names_required
            entities_to_put.append(badge_type)

    for badge_type in TopicExerciseBadgeType.all():

        # Make sure each TopicExerciseBadgeType has a corresponding topic...
        exists = len([t for t in topics if t.id == badge_type.topic_id]) > 0

        # ...if it doesn't, it may've been created by an old topic that has since been removed.
        # In this case, retire the badge.
        if not exists:
            badge_type.retired = True
            entities_to_put.append(badge_type)

    if entities_to_put:
        db.put(entities_to_put)

class TopicExerciseBadge(Badge):
    """ TopicExerciseBadge represents a single challenge patch for achieving proficiency
    in all constituent exercises of a Topic.

    TopicExerciseBadges are constructed by the data stored in
    TopicExerciseBadgeType datastore entities.
    """

    @staticmethod
    def all():
        badges = [TopicExerciseBadge(badge_type) for badge_type in TopicExerciseBadgeType.all()]
        return sorted(badges, key=lambda badge: badge.topic_standalone_title.lower())

    @staticmethod
    def name_for_topic_id(topic_id):
        return "topic_exercise_%s" % topic_id

    def __init__(self, topic_exercise_badge_type):
        Badge.__init__(self)

        # Set topic-specific properties
        self.topic_standalone_title = topic_exercise_badge_type.topic_standalone_title
        self.exercise_names_required = topic_exercise_badge_type.exercise_names_required

        # Set typical badge properties
        self.name = TopicExerciseBadge.name_for_topic_id(topic_exercise_badge_type.topic_id)
        self.description = self.topic_standalone_title
        self.points = 0
        self.badge_category = BadgeCategory.MASTER
        self.is_retired = topic_exercise_badge_type.retired
        self.is_hidden_if_unknown = self.is_retired

    def is_satisfied_by(self, *args, **kwargs):

        # This badge can't inherit from RetiredBadge because its Retired status
        # is set dynamically by topics, so it must handle self.is_retired
        # manually.
        if self.is_retired:
            return False

        user_data = kwargs.get("user_data", None)
        if user_data is None:
            return False

        if len(self.exercise_names_required) <= 0:
            return False

        # Make sure user is proficient in all topic exercises
        for exercise_name in self.exercise_names_required:
            if not user_data.is_proficient_at(exercise_name):
                return False

        return True

    def extended_description(self):
        return "Achieve proficiency in all skills in %s" % self.topic_standalone_title

    @property
    def icon_filename(self):
        """ Some topics will have custom icons pre-prepared, and some won't.
        To add a custom icon to a topic, add the topic's name to TOPICS_WITH_CUSTOM_ICONS
        below. Those without will use a default icon.

        Custom icon location and format:
        40x40px: /images/power-mode/badges/[lowercase-alphanumeric-and-dashes-only topic title]-40x40.png
        60x60px: /images/power-mode/badges/[lowercase-alphanumeric-and-dashes-only topic title]-60x60.png

        See /images/power-mode/badges/readme
        """

        if self.topic_standalone_title in TOPICS_WITH_CUSTOM_ICONS:
            return self.safe_topic_title_filename
        else:
            return "default"

    @property
    def safe_topic_title_filename(self):
        return slugify(self.topic_standalone_title)

    @property
    def compact_icon_src(self):
        return "/images/power-mode/badges/%s-40x40.png" % self.icon_filename

    @property
    def icon_src(self):
        return "/images/power-mode/badges/%s-60x60.png" % self.icon_filename

class TopicExerciseBadgeType(db.Model):
    """ Every time we publish a new topic tree,
    we make sure there is one TopicExerciseBadgeType for
    each topic that contains exercises.
    """

    topic_id = db.StringProperty()
    topic_standalone_title = db.StringProperty(indexed=False)
    exercise_names_required = object_property.TsvProperty(indexed=False)
    retired = db.BooleanProperty(default=False, indexed=False)

    @staticmethod
    def get_key_name(topic):
        return "topic:%s" % topic.id

    @staticmethod
    def get_or_insert_for_topic(topic):

        if not topic:
            return None

        key_name = TopicExerciseBadgeType.get_key_name(topic)
        topic_badge_type = TopicExerciseBadgeType.get_by_key_name(key_name)

        if not topic_badge_type:
            topic_badge_type = TopicExerciseBadgeType.get_or_insert(
                    key_name = key_name,
                    topic_id = topic.id,
                    topic_standalone_title = topic.standalone_title,
                    )

        return topic_badge_type

# TODO: when we find a nicer way of detecting existence of icons,
# use that. Couple ideas so far felt even grosser than this quick
# and easy hack.
TOPICS_WITH_CUSTOM_ICONS = frozenset([
    "Addition and subtraction",
    "Basic exponents",
    "Decimals",
    "Factors and multiples",
    "Fractions",
    "Multiplication and division",
    "Negative numbers",
    "Order of operations",
    "Percents",
    "Properties of numbers",
    "Ratios and proportions",
    "Solving linear equations",
])
