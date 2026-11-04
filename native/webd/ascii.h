/* Pictures as the same shaded, coloured characters the 3D icons use. Pure. */
#ifndef WEBD_ASCII_H
#define WEBD_ASCII_H

#include <stdint.h>

/* The tile for one colour: palette hue plus density, or 0 for nothing there. */
uint8_t ascii_tile(unsigned r, unsigned g, unsigned b);

/* An image (w x h, 3 bytes per pixel) fitted inside cols x rows of tiles and centred. out is cols * rows bytes.
 * The tiles are 8 x 12 pixels, which the fit allows for. */
void ascii_image(const uint8_t *rgb, int w, int h, int cols, int rows, uint8_t *out);

#endif
