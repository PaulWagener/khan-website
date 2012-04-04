(function() {
    // The video data for the subtopics of this topic
    var videosByTopic = {};

    // The currently selected subtopic in the content pane
    var selectedTopic = null;

    // The topic information for the current page's topic
    var rootPageTopic = null;

    // View for the root topic in the content pane
    var rootTopicView = null;

    // All the video information sorted by YouTube ID
    var videosDict = {};
    
    window.TopicPage = {
        init: function(rootPath, rootTopic) {
            var self = this;

            rootPageTopic = rootTopic;

            // TODO(tomyedwab): Temporary, should move this to a shared lib 
            Handlebars.registerPartial("youtube-player", Templates.get("shared.youtube-player"));

            videosDict[rootTopic.marqueeVideo.youtubeId] = rootTopic.marqueeVideo;
            _.each(rootTopic.subtopics, function(topic) {
                videosByTopic[topic.id] = topic;
                videosDict[topic.thumbnailLink.youtubeId] = topic.thumbnailLink;
            });

            $(".topic-page-content").on("click", ".topic-page-content a.subtopic-link", function() {
                selectedID = $(this).attr("data-id");
                self.router.navigate("/" + selectedID, true);
                return false;
            });

            $(".topic-page-content").on("click", "a.modal-video", function(ev) {
                var videoDesc = videosDict[$(this).attr("data-youtube-id")];
                if (videoDesc) {
                    var video = {
                        youtube_id: videoDesc.youtubeId,
                        relative_url: videoDesc.href,
                        title: videoDesc.title,
                        description: videoDesc.teaserHtml
                    };
                    ModalVideo.show(video);
                    ev.preventDefault();
                    return false;
                }
                return true;
            });

            this.router = new this.SubTopicRouter();
            this.router.bind("all", Analytics.handleRouterNavigation);
            Backbone.history.start({pushState: true, root: rootPath});
        },

        SubTopicRouter: Backbone.Router.extend({
            routes: {
                "*subtopicID": "subtopic"
            },

            subtopic: function(subtopicID) {
                var selectedTopicID = '';
                if (subtopicID.charAt(0) == '/') {
                    subtopicID = subtopicID.substr(1);
                }

                KAConsole.log("Switching to subtopic: " + subtopicID);
                if (subtopicID == "") {
                    selectedTopic = null;
                } else {
                    selectedTopic = videosByTopic[subtopicID] || null;
                }

                if (selectedTopic) {
                    selectedTopic.view = selectedTopic.view || new TopicPage.ContentTopicView({ model: selectedTopic });
                    selectedTopic.view.show();
                    selectedTopicID = selectedTopic.id;
                } else {
                    rootTopicView = rootTopicView || new TopicPage.RootTopicView({ model: rootPageTopic });
                    rootTopicView.show();
                }

                $(".topic-page-content .nav-pane")
                    .find("li.selected")
                        .removeClass("selected")
                        .end()
                    .find("li[data-id=\"" + selectedTopicID + "\"]")
                        .addClass("selected");

                $("body").scrollTop(0);
            }
        }),

        ContentTopicView: Backbone.View.extend({
            template: Templates.get("topic.content-topic-videos"),
            initialize: function() {
                this.render();
            },

            render: function() {
                $(this.el).html(this.template(this.model));
            },

            show: function() {
                $(".topic-page-content .content-pane")
                    .children()
                        .detach()
                        .end()
                    .append(this.el);
            }
        }),

        RootTopicView: Backbone.View.extend({
            template: Templates.get("topic.root-topic-view"),
            initialize: function() {
                this.render();
            },

            render: function() {
                $(this.el).html(this.template(this.model));
                VideoControls.initThumbnailHover($(this.el));
            },

            show: function() {
                $(".topic-page-content .content-pane")
                    .children()
                        .detach()
                        .end()
                    .append(this.el);
            }
        })
    };
})();
