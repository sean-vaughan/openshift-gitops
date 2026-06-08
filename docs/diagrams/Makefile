SRCS := $(wildcard src/*.d2)
SVGS := $(patsubst src/%.d2,img/%.svg,$(SRCS))

.PHONY: all clean watch

all: $(SVGS)

img/%.svg: src/%.d2
	d2 --layout=elk $< $@

clean:
	rm -f $(SVGS)

watch:
	@for f in src/*.d2; do \
	  name=$$(basename $$f .d2); \
	  d2 --watch --layout=elk $$f img/$${name}.svg & \
	done; \
	wait
