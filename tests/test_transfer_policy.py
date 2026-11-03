"""Redirect policy and dynamic segment re-planning tests."""

from __future__ import annotations

import time
from itertools import pairwise
from types import SimpleNamespace

import pytest

from idm.engine import segmented
from idm.engine import worker as worker_module
from idm.engine.manager import DownloadManager
from idm.engine.segmented import (
    MAX_SEGMENTS,
    Segment,
    SegmentPlan,
    journal_path,
    load_plan,
    plan_segments,
    save_plan,
)
from idm.engine.worker import DownloadWorker, _redirect_location
from idm.models.download_item import DownloadStatus
from tests.http_server import payload


def wait_until(app, predicate, timeout: float = 25.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(predicate())


def make_manager(**overrides) -> DownloadManager:
    options = {
        "max_concurrent": 3,
        "auto_retry": False,
        "max_retries": 0,
        "speed_limit_kbps": 0,
        "connections_per_download": 1,
    }
    options.update(overrides)
    return DownloadManager(SimpleNamespace(**options))


@pytest.fixture
def manager(qt_app):
    instance = make_manager()
    yield instance
    instance.shutdown()


def download(manager, url: str, folder, name: str):
    return manager.add_download(
        url=url, filename=name, folder=str(folder), category="Other Files"
    )


# -------------------------------------------------------------------- redirects
def test_redirect_chain_delivers_the_file(qt_app, server, manager, tmp_path) -> None:
    size = 96 * 1024
    item = download(
        manager,
        server.url(f"/redirect/{size}?to=/file/{size}&hops=3"),
        tmp_path,
        "chained.bin",
    )
    assert wait_until(qt_app, lambda: item.status == DownloadStatus.COMPLETED), item.error
    assert item.path.read_bytes() == payload(size)
    assert server.request_count(f"/redirect/{size}?to=/file/{size}&hops=3") == 1


def test_redirect_loop_fails_instead_of_crawling(
    qt_app, server, manager, tmp_path
) -> None:
    item = download(manager, server.url("/redirect/16?loop=1"), tmp_path, "loop.bin")
    assert wait_until(qt_app, lambda: item.status == DownloadStatus.FAILED, 20.0)
    assert "too many times" in item.error
    assert not item.path.exists()


def test_redirect_to_an_unsupported_address_is_refused(
    qt_app, server, manager, tmp_path
) -> None:
    item = download(
        manager,
        server.url("/redirect/16?to=file:///C:/Windows/win.ini"),
        tmp_path,
        "escaped.bin",
    )
    assert wait_until(qt_app, lambda: item.status == DownloadStatus.FAILED, 20.0)
    assert "unsupported address" in item.error


def test_segmented_download_through_a_redirect(
    qt_app, server, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(segmented, "MIN_SEGMENT_BYTES", 1024)
    monkeypatch.setattr(worker_module, "MIN_SEGMENT_BYTES", 1024)
    manager = make_manager(connections_per_download=4)
    try:
        size = 80 * 1024
        before = server.request_count(f"/file/{size}")
        item = download(
            manager,
            server.url(f"/redirect/{size}?to=/file/{size}"),
            tmp_path,
            "segmented.bin",
        )
        assert wait_until(
            qt_app, lambda: item.status == DownloadStatus.COMPLETED
        ), item.error
        assert item.path.read_bytes() == payload(size)
        assert server.request_count(f"/file/{size}") - before > 1, (
            "the redirected link was not fetched with several connections"
        )
    finally:
        manager.shutdown()


# ---------------------------------------------------------------- fake sessions
class _FakeResponse:
    def __init__(self, status: int, location: str = "", url: str = "") -> None:
        self.status_code = status
        self.headers = {"Location": location} if location else {}
        self.url = url

    def close(self) -> None:
        return None


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.auth = object()
        self.requested: list[str] = []
        self._responses = iter(responses)

    def get(self, url: str, **kwargs) -> _FakeResponse:
        self.requested.append(url)
        return next(self._responses)


def make_worker(qt_app, tmp_path, url: str = "http://localhost/start") -> DownloadWorker:
    return DownloadWorker(
        "dl-redirect",
        url,
        str(tmp_path),
        "out.bin",
        auto_retry=False,
        max_retries=0,
        limiter=worker_module.SpeedLimiter(0),
    )


def test_credentials_stay_with_the_authenticated_host(qt_app, tmp_path) -> None:
    worker = make_worker(qt_app, tmp_path)
    session = _FakeSession(
        [
            _FakeResponse(302, "http://127.0.0.1/mirror"),
            _FakeResponse(200, url="http://127.0.0.1/mirror"),
        ]
    )
    response = worker._get_stream(session, "http://localhost/start", {})
    assert response.status_code == 200
    assert session.requested == ["http://localhost/start", "http://127.0.0.1/mirror"]
    assert session.auth is None


def test_credentials_survive_a_same_host_redirect(qt_app, tmp_path) -> None:
    worker = make_worker(qt_app, tmp_path)
    session = _FakeSession(
        [
            _FakeResponse(302, "https://localhost/secure"),
            _FakeResponse(200, url="https://localhost/secure"),
        ]
    )
    response = worker._get_stream(session, "http://localhost/start", {})
    assert response.status_code == 200
    assert session.auth is not None


def test_relative_redirect_target_is_resolved(qt_app, tmp_path) -> None:
    worker = make_worker(qt_app, tmp_path)
    session = _FakeSession(
        [_FakeResponse(302, "/files/next"), _FakeResponse(200, url="http://localhost/x")]
    )
    worker._get_stream(session, "http://localhost/dir/start", {})
    assert session.requested[1] == "http://localhost/files/next"


def test_too_many_hops_stops_at_the_limit(qt_app, tmp_path) -> None:
    worker = make_worker(qt_app, tmp_path)
    hops = [_FakeResponse(302, f"/hop/{index}") for index in range(30)]
    hops.append(_FakeResponse(200, url="http://localhost/late"))
    session = _FakeSession(hops)
    with pytest.raises(worker_module._FatalError) as caught:
        worker._get_stream(session, "http://localhost/start", {})
    assert "too many times" in str(caught.value)
    assert len(session.requested) == worker_module._MAX_REDIRECT_HOPS + 1


def test_unsupported_redirect_scheme_stops_the_chain(qt_app, tmp_path) -> None:
    worker = make_worker(qt_app, tmp_path)
    session = _FakeSession([_FakeResponse(302, "ftp://files.example.com/a.zip")])
    with pytest.raises(worker_module._FatalError) as caught:
        worker._get_stream(session, "http://localhost/start", {})
    assert "unsupported address" in str(caught.value)
    assert len(session.requested) == 1


def test_only_redirect_statuses_continue_a_chain() -> None:
    assert _redirect_location(_FakeResponse(200, "/x")) is None
    assert _redirect_location(_FakeResponse(304, "/x")) is None
    assert _redirect_location(_FakeResponse(302)) is None
    assert _redirect_location(_FakeResponse(308, "/x")) == "/x"


# ------------------------------------------------------------------ re-planning
def _plan(count: int = 4, segment_bytes: int = 16 * 1024) -> SegmentPlan:
    segments = [
        Segment(
            index=index,
            start=index * segment_bytes,
            end=(index + 1) * segment_bytes - 1,
        )
        for index in range(count)
    ]
    return SegmentPlan(
        total=count * segment_bytes,
        url="https://example.com/big.bin",
        etag="",
        last_modified="",
        segments=segments,
    )


def test_idle_connection_receives_half_of_the_slowest_tail() -> None:
    plan = _plan()
    idle, second, third, least_done = plan.segments
    idle.done = idle.length
    second.done = 4 * 1024
    third.done = 2 * 1024
    donor = max(plan.segments[1:], key=lambda segment: segment.remaining)
    assert donor is least_done

    taken = plan.replan_for(idle, 1024)

    assert taken is not None
    assert taken in plan.segments
    assert donor.end == taken.start - 1
    assert taken.length >= 1024
    assert donor.remaining >= 1024
    assert [segment.index for segment in plan.segments] == list(
        range(len(plan.segments))
    )
    for previous, current in pairwise(plan.segments):
        assert current.start == previous.end + 1
    assert plan.segments[-1].end == plan.total - 1


def test_replanning_never_loses_or_duplicates_bytes() -> None:
    plan = _plan()
    idle = plan.segments[0]
    idle.done = idle.length
    while True:
        taken = plan.replan_for(idle, 1024)
        if taken is None:
            break
        taken.done = taken.length
        idle = taken
    assert sum(segment.length for segment in plan.segments) == plan.total
    restored = SegmentPlan.from_record(plan.to_record())
    assert restored is not None
    assert sum(segment.length for segment in restored.segments) == plan.total


def test_claimed_and_finished_bytes_are_not_donors() -> None:
    plan = _plan()
    idle, donor = plan.segments[0], plan.segments[1]
    idle.done = idle.length
    donor.claimed_until = donor.end
    for segment in plan.segments[2:]:
        segment.done = segment.length

    assert plan.replan_for(idle, 1024) is None


def test_replanning_stops_at_the_segment_limit() -> None:
    plan = _plan(count=MAX_SEGMENTS)
    idle = plan.segments[0]
    idle.done = idle.length
    assert plan.replan_for(idle, 1024) is None


def test_journal_written_after_a_replan_is_loadable(tmp_path) -> None:
    plan = _plan()
    part = tmp_path / "big.bin.idm.part"
    part.write_bytes(b"\0" * plan.total)
    idle = plan.segments[0]
    idle.done = idle.length
    assert plan.replan_for(idle, 1024) is not None
    assert save_plan(part, plan)
    restored = load_plan(part)
    assert restored is not None
    assert len(restored.segments) == len(plan.segments)
    assert restored.complete is False
    assert Segment(index=0, start=0, end=9, done=5).remaining == 5


# ------------------------------------------------------------- end to end steal
def run_segmented(qt_app, server, tmp_path, monkeypatch, size: int, connections: int):
    monkeypatch.setattr(segmented, "MIN_SEGMENT_BYTES", 1024)
    monkeypatch.setattr(worker_module, "MIN_SEGMENT_BYTES", 1024)
    monkeypatch.setattr(worker_module, "_GRANT_BYTES", 4096)
    url = server.url(f"/file/{size}")
    worker = DownloadWorker(
        "dl-steal",
        url,
        str(tmp_path),
        "steal.bin",
        auto_retry=False,
        max_retries=0,
        limiter=worker_module.SpeedLimiter(0),
        connections=connections,
    )
    worker.part_path.touch()
    plan = SegmentPlan(
        total=size,
        url=url,
        etag="",
        last_modified="",
        segments=plan_segments(size, connections),
    )
    return worker, plan


def test_a_stalled_segment_is_adopted_and_the_file_is_exact(
    qt_app, server, tmp_path, monkeypatch
) -> None:
    size = 64 * 1024
    worker, plan = run_segmented(qt_app, server, tmp_path, monkeypatch, size, 4)
    stalled = plan.segments[1]
    original = DownloadWorker._segment_request
    stall_used = []

    def slowed(self, segment, active_plan, stop_event, session):
        if segment is stalled and not stall_used:
            stall_used.append(True)
            time.sleep(0.6)
        return original(self, segment, active_plan, stop_event, session)

    monkeypatch.setattr(DownloadWorker, "_segment_request", slowed)
    outcome = worker._run_segmented(plan, fresh=True)

    assert outcome == DownloadStatus.COMPLETED
    assert (tmp_path / "steal.bin").read_bytes() == payload(size)
    assert len(plan.segments) > 4, "no segment was ever re-planned"
    assert not journal_path(worker.part_path).exists()


def test_replanned_transfer_resumes_from_the_journal(
    qt_app, server, tmp_path, monkeypatch
) -> None:
    size = 64 * 1024
    worker, plan = run_segmented(qt_app, server, tmp_path, monkeypatch, size, 4)
    stalled = plan.segments[1]
    original = DownloadWorker._segment_request
    stall_used = []

    def slowed(self, segment, active_plan, stop_event, session):
        if segment is stalled and not stall_used:
            stall_used.append(True)
            time.sleep(0.6)
        return original(self, segment, active_plan, stop_event, session)

    def pause_after_replan(self, segment, active_plan, stop_event, session):
        result = slowed(self, segment, active_plan, stop_event, session)
        if len(active_plan.segments) > 4:
            self.request_pause()
        return result

    monkeypatch.setattr(DownloadWorker, "_segment_request", pause_after_replan)
    outcome = worker._run_segmented(plan, fresh=True)
    assert outcome == DownloadStatus.PAUSED

    journaled = load_plan(worker.part_path)
    assert journaled is not None
    assert len(journaled.segments) > 4
    assert 0 < journaled.downloaded < size

    monkeypatch.setattr(DownloadWorker, "_segment_request", original)
    resumed = DownloadWorker(
        "dl-steal2",
        server.url(f"/file/{size}"),
        str(tmp_path),
        "steal.bin",
        auto_retry=False,
        max_retries=0,
        limiter=worker_module.SpeedLimiter(0),
        connections=4,
    )
    assert resumed._run_segmented(journaled, fresh=False) == DownloadStatus.COMPLETED
    assert (tmp_path / "steal.bin").read_bytes() == payload(size)
