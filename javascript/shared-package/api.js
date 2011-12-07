// Hello friend!
// APIActionResults is an observer for all XHR responses that go through the page
// The key being that it will listen for XHR messages with the magic header "X-KA-API-Response"
// which is added in from api/__init__.py
// 
// In api/v1.py, add_action_results takes care of bundling data to be digested by this client-side
// listener. As a result, if you have something which happens as a result of an API POST, it's worth
// investigating whether or not you can have it triggered here rather than in khan-exercise.js
var APIActionResults = {

    init: function() {
        this.hooks = [];

        $(document).ajaxComplete(function (e, xhr, settings) {

            if (xhr && 
                xhr.getResponseHeader('X-KA-API-Response') && 
                xhr.responseText) {

                try { eval("var result = " + xhr.responseText); }
                catch(e) { return; }

                if (result && result.action_results) {
                    $(APIActionResults.hooks).each(function(ix, el) {
                        if (typeof result.action_results[el.prop] !== "undefined") {
                            el.fxn(result.action_results[el.prop]);
                        }
                    });
                }
            }
        });

        jQuery.ajaxSetup({
            beforeSend: function(xhr, settings) {
                if (settings && settings.url && settings.url.indexOf("/api/") > -1) {
                    if (fkey) {
                        // Send xsrf token along via header so it can be matched up
                        // w/ cookie value.
                        xhr.setRequestHeader("X_KA_FKEY", fkey);
                    }
                }
            }
        });

    },

    register: function(prop, fxn) {
        this.hooks[this.hooks.length] = {prop: prop, fxn: fxn};
    }
};

APIActionResults.init();

// Show any badges that were awarded w/ any API ajax request
$(function(){ APIActionResults.register("badges_earned_html", Badges.show); });

// Show any login notifications that pop up w/ any API ajax request
$(function(){ APIActionResults.register("login_notifications_html", Notifications.show); });

// Update user info after appropriate API ajax requests
$(function(){ APIActionResults.register("user_info_html", 
        function(sUserInfoHtml) {
            $("#user-info").html(sUserInfoHtml);
        }
    );
});

// show point animation above progress bar when in exercise pages
$(function(){ 

  var updatePointDisplay = function( data ) {
    if( jQuery(".single-exercise").length > 0 && data.points > 0) {
      var coin = jQuery("<div>+"+data.points+"</div>").addClass("energy-points-badge");
      jQuery(".streak-bar").append(coin);
      jQuery(coin)
        .fadeIn(195)
        .delay(650)
        .animate({top:"-30", opacity:0}, 350, "easeInOutCubic",
          function(){jQuery(coin).hide(0).remove();}); // remove coin on animation complete
    }
  };

  APIActionResults.register( "points_earned", updatePointDisplay );
});

// TODO(david): I don't think we need to wait for DOM ready to register some of
//     these handlers.
// TODO(david): move to pageutil.js
// Change review mode heading to "review done!" if appropriate
$(function() {
	APIActionResults.register( "review_done", Review.highlightDone );
});
