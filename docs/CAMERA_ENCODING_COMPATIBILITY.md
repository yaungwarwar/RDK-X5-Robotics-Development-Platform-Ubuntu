# Camera image encodings and validation

No actual GS130WI encoding or topic type was inspected in Phase B. Selection is explicit and fixed: raw `sensor_msgs/Image` on the chosen raw topic, or `sensor_msgs/CompressedImage` on `/image_combine_jpeg` for the combined view. QoS, actual types and the named compressed publisher must be established separately on the target.

| Input | Implemented handling |
|---|---|
| `rgb8`, `bgr8`, `mono8` | Validate dimensions (1–1280 by 1–720), row stride and exact buffer length before copying; maximum raw bytes 2,764,800. Convert with standard-library zlib into PNG. Padding up to 4096 bytes per row is permitted only within the total cap. |
| Other raw encodings, including Bayer, YUV, `rgba8`, 16-bit or vendor formats | Explicitly rejected; no guessing or implicit conversion. |
| PNG compressed | Max 2 MiB; validate signature, dimensions, chunk boundaries, CRCs, required IDAT/IEND and count cap. Browser performs image decode. |
| JPEG compressed | Max 2 MiB; validate SOI/EOI, marker segment lengths and supported SOF dimensions. Browser performs full decode; this is structural prevalidation, not a complete JPEG entropy decoder. |
| Other compressed formats | Explicitly rejected. |

Conversion runs in the native child, never on the telemetry collector. Image output is bounded to 2 MiB; the broker validates framing, MIME, dimensions and image signature again. A browser decode failure is explicit and no ACK is sent. Validated metadata does not prove a hostile image is safe to decode or that the format is compatible with a physical camera. Confirm endianness, exact `step`, format strings, lengths, orientation and timestamp semantics against the real publisher before authorizing bench streaming. No device-specific assumptions are substituted for observation.

## B.1 local-only NV12 correction

After a separately authorized metadata-only physical observation identified `nv12` at 1088×1280, stride 1088 and 2,088,960 bytes, the user approved local compatibility work. The workstation worker accepts even NV12 width/height/stride up to 1280×1280, verifies exact `step × height × 3 / 2` length and retains the existing 2,764,800-byte raw limit. It outputs **grayscale Y-plane luminance**, explicitly labelled in the UI; UV chroma is not rendered. Output/IPC remains at most 2 MiB. The original 720-pixel height limit remains for other raw encodings and compressed images. Calibration metadata can use dimensions up to 1280×1280. Synthetic tests reproduce the observed layout without retaining any physical image; physical decode, color accuracy and sustained target performance remain unvalidated.
