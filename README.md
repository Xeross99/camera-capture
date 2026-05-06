# Camera Capture

A tethered product-photography pipeline for an e-commerce shop.
Hit `ENTER` in the terminal: a Canon EOS M50 fires, the background is
removed, the product is centered and watermarked, and a 1500×1500 JPEG
lands on disk ready to upload.

![Setup](assets/readme/setup.jpg)

## Why I built this

Every new product in an online shop needs catalog photos: clean white
background, centered, consistent crop, watermarked. Doing this by hand
in Lightroom for a batch of products eats a chunk of time. I wanted
three keystrokes and a coffee instead.

## How fast it is

The three photos in `assets/readme/buffer_stop_*.jpg` were captured in a
single session in **about 20 seconds**. Each cycle (shutter, USB
download, background removal, center, watermark, save) takes roughly
seven seconds on a MacBook Pro with an M4 chip. I rotate the product on
the turntable between shots and press ENTER. That is the whole loop.

## Before / after

Raw images are straight off the 24 MP sensor. Processed ones are what
the tool writes: 1500×1500, white background, centered, watermarked.
Note the third shot was intentionally taken at an angle. The pipeline
does *not* "straighten" it, because a three-quarter view is exactly
what you want on a product page.

| Raw | Processed |
|---|---|
| ![Raw 1](assets/readme/buffer_stop_1_raw.jpg) | ![Processed 1](assets/readme/buffer_stop_1.jpg) |
| ![Raw 2](assets/readme/buffer_stop_2_raw.jpg) | ![Processed 2](assets/readme/buffer_stop_2.jpg) |
| ![Raw 3](assets/readme/buffer_stop_3_raw.jpg) | ![Processed 3](assets/readme/buffer_stop_3.jpg) |

## How it works

One pass, full sensor resolution, one final resize. No SaaS calls,
nothing leaves the machine.

1. `gphoto2` triggers the shutter and pulls a 6000×4000 JPEG over USB.
2. `rembg` (model `u2netp`) runs locally on CPU and produces an alpha
   mask.
3. Small mask blobs (dust, paper edges) are filtered out by area.
4. Shadows visible *through gaps in the product* are lifted to white,
   while the gray plastic body itself is left alone.
5. Bounding box, square crop with a fixed margin, resize to 1500×1500.
6. Unsharp mask on the product only, never on the background, so no
   halo on alpha edges.
7. Semi-transparent `TRIXBRIX.eu` watermark in the bottom right.
8. Both the raw camera JPEG and the final 1500×1500 are saved to
   `photos/<product-name>/`.

## Run it

```bash
source .venv/bin/activate
python3 main.py
```

Interactive controls:

- `ENTER` take a shot
- `n` change the destination folder name
- `b` toggle background removal
- `q` quit

Or re-process an existing file without the camera:

```bash
python3 main.py --input some_photo.jpg --name my_product
```

## Stack

Python 3.12 + `python-gphoto2`, `rembg`, `onnxruntime`, `Pillow`,
`numpy`, `scipy.ndimage`, `rich`. No GPU, no cloud, runs offline.
