FROM ubuntu:14.04
RUN sed -i 's|http://archive.ubuntu.com|http://archive.ubuntu.com|' /etc/apt/sources.list && apt-get update && \
    apt-get install -y --no-install-recommends gcc-4.7-arm-linux-gnueabi gcc-arm-linux-gnueabi make bc gcc libc6-dev perl python && \
    ln -sf /usr/bin/arm-linux-gnueabi-gcc-4.7 /usr/local/bin/arm-linux-gnueabi-gcc47 && rm -rf /var/lib/apt/lists/*
