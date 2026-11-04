/* A page or a picture from the internet: redirects followed, gzip undone. Everything webd fetches goes here. */
#ifndef WEBD_FETCH_H
#define WEBD_FETCH_H

#include <stdint.h>

#include "net.h"

/* req.url is replaced as redirects are followed; the URL ended up at goes in final (4096 bytes). */
int fetch_follow(net_request req, net_response *resp, char *final);

/* Decode a picture to tiles: WEB_ART_COLS wide, rows tall. 1 if it worked. */
int fetch_decode_art(const char *data, size_t n, int rows, uint8_t *out);

#endif
