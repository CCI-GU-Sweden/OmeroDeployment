FROM openmicroscopy/omero-web-standalone:5

USER root


RUN chmod 777 /opt/omero

RUN git clone https://github.com/jmuhlich/omero-oauth.git

RUN ls /opt

RUN /opt/omero/web/venv3/bin/python /opt/setup/omero-oauth/setup.py install
