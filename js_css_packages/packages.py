# Initialize flag and caches of the package list.
_debug = False
_javascript = None
_stylesheets = None

def set_debug(debug=False):
    global _debug
    global _javascript
    global _stylesheets
    if _debug != debug:
        _debug = debug
        # Clear out caches
        _javascript = None
        _stylesheets = None

def get_javascript():
    return _javascript or {
        "shared": {
            "files": [
                "jquery.js",
                "jquery-ui.js",
                "jquery.ui.menu.js",
                "jquery.watermark.js",
                "jquery.placeholder.js",
                "jquery.hoverflow.js",
                "pageutil.js",
                "api.js",
                "social.js",
                "../../gae_bingo/static/js/gae_bingo.js",
                "handlebars.js" if _debug else "handlebars.vm.js",
                "templates.js",
                "underscore.js",
            ]
        },
        "video": {
            "files": [
                "jquery.qtip.js",
                "jquery.tmpl.min.js",
                "bootstrap-modal.js",
                "video.js",
                "discussion.js",
                "modalvideo.js",
            ]
        },
        "homepage": {
            "files": [
                "jquery.easing.1.3.js",
                "jquery.cycle.all.min.js",
                "waypoints.min.js",
                "homepage.js",
                "ga_social_tracking.js",
            ]
        },
        "exercisestats": {
            "files": [
                "highcharts.js",
            ]
        },
        "profile": {
            "templates": [
                "profile.handlebars",
            ],
            "files": [
                "jquery.address-1.4.min.js",
                "highcharts.js",
                "profile.js",
            ]
        },
        "maps": {
            "files": [
                "fastmarkeroverlay.js",
                "knowledgemap.js",
            ]
        },
        "mobile": {
            "files": [
                "jquery.js",
                "jquery.mobile-1.0a4.1.js",
                "iscroll-lite.min.js",
                "mobile.js",
            ]
        },
        "studentlists": {
            "files": [
                "studentlists.js",
                "classprofile.js",
            ]
        },
        "exercises": {
            "base_path": "../khan-exercises",
            "base_url": "/khan-exercises",
            "files": [
                "khan-exercise.js",
                "utils/angles.js",
                "utils/answer-types.js",
                "utils/calculus.js",
                "utils/congruence.js",
                "utils/convert-values.js",
                "utils/d3.js",
                "utils/derivative-intuition.js",
                "utils/exponents.js",
                "utils/expressions.js",
                "utils/functional.js",
                "utils/graphie-geometry.js",
                "utils/graphie-helpers-arithmetic.js",
                "utils/graphie-helpers.js",
                "utils/graphie-polygon.js",
                "utils/graphie.js",
                "utils/interactive.js",
                "utils/jquery-color.js",
                "utils/jquery.mobile.vmouse.js",
                "utils/math-format.js",
                "utils/math.js",
                "utils/mean-and-median.js",
                "utils/parabola-intuition.js",
                "utils/polynomials.js",
                "utils/probability.js",
                "utils/raphael.js",
                "utils/scratchpad.js",
                "utils/slice-clone.js",
                "utils/stat.js",
                "utils/tmpl.js",
                "utils/word-problems.js",
                "utils/spin.js",
                "utils/unit-circle.js",
            ]
        },
    }

def get_stylesheets():
    return _stylesheets or {
        "shared": {
            "files": [
                "default.css",
                "rating.css",
                "stylesheet.css",
                "menu.css",
                "profile.css",
                "museo-sans.css",
                "jquery-ui-1.8.4.custom.css",
            ]
        },
        "mobile": {
            "files": [
                "jquery.mobile-1.0a4.1.css",
                "mobile.css",
            ]
        },
        "video": {
            "files": [
                "jquery.qtip.css",
                "video.css",
                "discussion.css",
                "modalvideo.css",
            ]
        },
        "studentlists": {
            "files": [
                "viewstudentlists.css",
                "viewclassprofile.css",
            ]
        },
        "exercises": {
            "base_path": "../khan-exercises/css",
            "base_url": "/khan-exercises/css",
            "files": [
                "khan-exercise.css",
            ]
        },
    }
