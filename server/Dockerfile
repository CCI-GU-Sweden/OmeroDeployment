FROM openmicroscopy/omero-server:5.6

USER root

RUN chmod 777 /opt/omero

RUN mkdir /build_tmp
RUN cp -r /opt/omero/server/OMERO.server/* /build_tmp/
RUN mkdir /build_tmp2
RUN cp -r /OMERO/* /build_tmp2

