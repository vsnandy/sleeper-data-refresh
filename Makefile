.PHONY: build deploy test

build:
	sam build

deploy:
	sam deploy --guided

test:
	pytest -v
