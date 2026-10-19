# ArduPilot SITL (software-in-the-loop): the real ArduCopter flight code built for the host CPU.
FROM ubuntu:22.04 AS build
ARG AP_TAG=Copter-4.7.1
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates python3 python3-pip g++ gcc make pkg-config && rm -rf /var/lib/apt/lists/* \
 && pip3 install --no-cache-dir empy==3.3.4 pexpect future
RUN git clone --depth 1 --branch ${AP_TAG} --recurse-submodules --shallow-submodules \
      https://github.com/ArduPilot/ardupilot.git /ardupilot
WORKDIR /ardupilot
RUN ./waf configure --board sitl && ./waf copter

FROM python:3.12-slim
RUN pip install --no-cache-dir pymavlink==2.4.50
COPY --from=build /ardupilot/build/sitl/bin/arducopter /usr/local/bin/arducopter
COPY --from=build /ardupilot/Tools/autotest/default_params/copter.parm /opt/sitl/copter.parm
COPY sixg.parm /opt/sitl/sixg.parm
COPY mission.py /opt/sitl/mission.py
COPY run-sitl.sh /usr/local/bin/run-sitl.sh
WORKDIR /opt/sitl
ENTRYPOINT ["/usr/local/bin/run-sitl.sh"]
