FROM docker.io/openmicroscopy/omero-server:5.6
USER 0
RUN dnf -y update-minimal --setopt=tsflags=nodocs --security && \
    dnf -y install --setopt=tsflags=nodocs python3-pip htop && \
    dnf clean all
RUN /usr/bin/pip install reportlab markdown
