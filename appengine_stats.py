from __future__ import absolute_import
import datetime
import time

import request_handler
from google.appengine.api import memcache

class MemcacheStatus(request_handler.RequestHandler):
    """
    Handles request to show information about the current state of memcache.

    Gives raw data, suitable for plotting.
    TODO(csilvers): save the data and show a pretty graphy.
    """

    def get(self):
        now = datetime.datetime.now()
        now_time_t = int(time.mktime(now.timetuple()))
        memcache_stats = memcache.get_stats()

        if self.request.get('output') in ('text', 'txt'):
            self.response.out.write(now_time_t)
            self.response.out.write(' h:%(hits)s'
                                    ' m:%(misses)s'
                                    ' bh:%(byte_hits)s'
                                    ' i:%(items)s'
                                    ' b:%(bytes)s'
                                    ' oia:%(oldest_item_age)s'
                                    '\n' % memcache_stats)
            self.response.headers['Content-Type'] = "text/text"
        else:
            template_values = {
                'now': now.ctime(),
                'now_time_t': now_time_t,
                'memcache_stats': memcache_stats,
            }
            self.render_jinja2_template("memcache_stats.html", template_values)
