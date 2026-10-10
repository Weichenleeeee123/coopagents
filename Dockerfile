FROM python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY deploy/constraints.txt ./constraints.txt
RUN pip install --no-cache-dir -c constraints.txt '.[service]' \
    && groupadd --gid 10001 crewmesh \
    && useradd --uid 10001 --gid crewmesh --no-create-home crewmesh \
    && mkdir /data && chown crewmesh:crewmesh /data
USER 10001:10001
ENV CREWMESH_DATABASE=/data/crewmesh.sqlite3
EXPOSE 8787
CMD ["python", "-m", "crewmesh.server"]
