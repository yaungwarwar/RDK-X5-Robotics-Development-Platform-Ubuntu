"""Exercise every benchmark option through existing image validation and bounded IPC."""

import asyncio

import pytest

from camera_nv12_benchmark import VARIANTS, convert, fixture


@pytest.mark.parametrize("variant", VARIANTS)
def test_benchmark_variant_uses_bounded_frame_and_protocol(variant):
    from native_protocol import MAX_PAYLOAD, pack_record, read_record
    from server import LatestFrame

    data, mime, width, height, encoding = convert(fixture("high"), variant)
    assert len(data) <= MAX_PAYLOAD and mime == "image/png" and encoding == "nv12"
    record = pack_record({"type": "frame", "width": width, "height": height}, data)

    async def check():
        reader = asyncio.StreamReader()
        reader.feed_data(record)
        header, payload = await read_record(reader)
        slot = LatestFrame()
        slot.report_error("diagnostic fixture")
        slot.publish_native(payload, header)
        slot.publish_native(payload, header)
        assert len(slot.errors) == 1 and slot.error_overflow == 0
        assert slot.sequence == 2 and slot.frame[0] == 2
        assert slot.event.is_set()

    asyncio.run(check())
