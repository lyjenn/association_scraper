from scraper_app.proxy.manager import ProxyManager, parse_proxy_line


def test_parse_proxy_line_http():
    p = parse_proxy_line("http://user:pass@1.2.3.4:8080")
    assert p is not None
    assert p.host == "1.2.3.4"
    assert p.port == 8080
    assert p.username == "user"
    assert p.to_playwright()["server"] == "http://1.2.3.4:8080"


def test_parse_socks5():
    p = parse_proxy_line("socks5://10.0.0.1:1080")
    assert p is not None
    assert p.scheme == "socks5"


def test_records_per_proxy_rotation():
    lines = [
        "http://127.0.0.1:9001",
        "http://127.0.0.1:9002",
        "http://127.0.0.1:9003",
    ]
    mgr = ProxyManager.from_lines(lines, records_per_proxy=2)
    assert mgr.current is not None
    assert mgr.current.port == 9001

    mgr.mark_record_complete()
    assert not mgr.should_rotate()
    mgr.mark_record_complete()
    assert mgr.should_rotate()

    nxt = mgr.rotate()
    assert nxt is not None
    assert nxt.port == 9002
    assert mgr.records_on_current == 0
    assert mgr.last_rotation is not None

    mgr.mark_record_complete()
    mgr.mark_record_complete()
    mgr.rotate()
    assert mgr.current.port == 9003


def test_direct_mode_when_empty():
    mgr = ProxyManager.from_lines([], records_per_proxy=5)
    assert mgr.direct_mode
    assert mgr.playwright_proxy() is None
    mgr.mark_record_complete()
    assert not mgr.should_rotate()
