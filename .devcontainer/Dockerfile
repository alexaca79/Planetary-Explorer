# syntax=docker/dockerfile:1

FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

ENV PIP_INDEX_URL=https://packagefeedproxy.microsoft.io/pypi/simple \
    NPM_CONFIG_REGISTRY=https://packagefeedproxy.microsoft.io/npm/ \
    YARN_NPM_REGISTRY_SERVER=https://packagefeedproxy.microsoft.io/npm/ \
    NUGET_CFS_SOURCE=https://packagefeedproxy.microsoft.io/nuget/v3/index.json \
    NUGET_PACKAGES=/home/vscode/.nuget/packages \
    VIRTUAL_ENV=/home/vscode/.venvs/planetary-explorer \
    PATH=/home/vscode/.venvs/planetary-explorer/bin:${PATH} \
    GDAL_CONFIG=/usr/bin/gdal-config \
    CPLUS_INCLUDE_PATH=/usr/include/gdal \
    C_INCLUDE_PATH=/usr/include/gdal \
    GDAL_SKIP=netCDF

USER root

RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update \
    && apt-get install --yes --no-install-recommends \
        build-essential \
        gdal-bin \
        git-lfs \
        jq \
        libexpat1-dev \
        libgdal-dev \
        libgeos-dev \
        libproj-dev \
        libxml2-dev \
        proj-bin \
        shellcheck \
    && rm -rf /var/lib/apt/lists/*

COPY .devcontainer/NuGet.Config /home/vscode/.nuget/NuGet/NuGet.Config

RUN mkdir -p "${NUGET_PACKAGES}" /home/vscode/.venvs \
    && chown -R vscode:vscode /home/vscode/.nuget /home/vscode/.venvs

USER vscode
