FROM docker:27-dind

RUN apk update && apk upgrade
RUN apk add github-cli python3 py3-pip openssh-client rsync

RUN pip install wheel --break-system-packages && pip install colorama requests --break-system-packages

RUN mkdir -p /root/.ssh


COPY src /root/src
WORKDIR /root/src

COPY id_ed25519* /root/.ssh/

RUN chmod 600 /root/.ssh/*

CMD [ "python3", "main.py" ]

EXPOSE 8888