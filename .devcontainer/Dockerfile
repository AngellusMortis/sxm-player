FROM python:3.9.6-slim-buster

RUN apt-get update \
    && apt-get install -y git ffmpeg build-essential vim \
    # cleaning up unused files
    && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
    && rm -rf /var/lib/apt/lists/*

COPY dev-requirements.txt /dev-requirements.txt
RUN pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir -r /dev-requirements.txt \
    && rm /dev-requirements.txt \
    && echo 'export PS1="\[$(tput setaf 6)\]\w \[$(tput setaf 7)\]\\$ \[$(tput sgr0)\]"' >> /root/.bashrc

ENV PATH /workspaces/sxm-player/.bin:$PATH
ENV PYTHONPATH /workspaces/sxm-player/:/workspaces/sxm-client/
ENV FLIT_ROOT_INSTALL=1
