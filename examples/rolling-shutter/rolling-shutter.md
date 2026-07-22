# Rolling-shutter camera distortion

This original note was written for the techshort demonstration. It does not reproduce a paper, article, or protected figure.

## Rolling shutter and motion

A rolling-shutter sensor does not expose every image row at the same instant. Instead, it starts or reads rows in sequence over a frame-readout interval. If an object or camera moves during that interval, each row records a slightly different moment. When the rows are assembled, a straight moving edge can appear slanted and a rotating blade can appear curved.

Faster motion or a longer frame readout increases the visible skew. A simple demonstration assigns row 0 to time 0 ms and row 1000 to time 20 ms. If an edge moves horizontally at 1 image-width per second during that readout, the top-row offset is 0% and the bottom row records the edge about 2% of an image-width later.

## Engineering comparison

A global shutter exposes all rows together and therefore avoids this row-timing skew. Some rolling-shutter cameras reduce the effect by reading the sensor faster. A faster readout reduces distortion, but it does not guarantee a perfectly undistorted image. Motion blur, lens distortion, stabilization, resampling, and image processing can still change recorded geometry.

## Scope and limitation

This simplified description assumes a steady readout direction and motion during one frame. Real sensors may use different timing patterns, and real scenes can combine translation, rotation, changing illumination, and depth. The model explains a mechanism; it does not recover the true shape of every moving object from one frame.
