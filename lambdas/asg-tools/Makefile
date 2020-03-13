#!make

SHELL := $(shell which bash)
BUILDER_IMAGE_NAME := $(shell basename $(CURDIR))
ARTEFACT_NAME := lambda.zip

.PHONY: build clean

help:
	@echo "Please use 'make <target>' where <target> is one of"
	@echo "  build         Build $(ARTEFACT_NAME) artefact"
	@echo "  clean         Removes build artefacts"

build:
	@{ \
	  docker build -t $(BUILDER_IMAGE_NAME) . && \
	  docker create $(BUILDER_IMAGE_NAME) /bin/true \
		| while read BUILDER_CONTAINER_ID; do \
			docker cp $$BUILDER_CONTAINER_ID:/$(ARTEFACT_NAME) . ; \
			docker rm $$BUILDER_CONTAINER_ID ; \
		  done; \
	  docker rmi -f $(BUILDER_IMAGE_NAME) ; \
	} > /dev/null

clean:
	@rm -f $(ARTEFACT_NAME)

