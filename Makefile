.PHONY: run demo debug-scroll check
run:
	uv run python -m kanitor
demo:
	uv run python -m kanitor --root examples/demo
debug-scroll:
	uv run python dev/trace_scroll.py -- $(ARGS)
check:
	uv run --extra mcp python -m unittest discover -s tests -v
	node --check kanitor/bridge.cjs
	node --check kanitor/work/subject.cjs
