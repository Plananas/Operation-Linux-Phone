/* HTML to rows. Pure, and forgiving: there's no tree, only a walk over the tags with a little state, and no
 * JavaScript or stylesheets. */
#ifndef WEBD_HTML_H
#define WEBD_HTML_H

#include <stddef.h>

#include "doc.h"

enum { HTML_IMAGES_MAX = 12 };   /* the most pictures a page gets */

typedef struct {
	int width;
	int inline_urls;               /* write out each link's address, for the agent to read */
	int keep_nav;                  /* keep <nav> and <aside>, which are usually menus */
} html_options;

void html_layout(const char *html, size_t n, const char *base_url, html_options opt, doc *out);

/* The value of an attribute in the text between < and >, as UTF-8 with entities decoded. 0 if it isn't there. */
int html_attr(const char *tag, size_t tag_n, const char *name, char *out, size_t cap);

#endif
