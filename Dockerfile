FROM python:3.6-slim AS builder
RUN printf '%s\n' \
	'deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/20260608T000000Z bullseye main' \
	'deb [check-valid-until=no] http://snapshot.debian.org/archive/debian-security/20260608T021553Z bullseye-security main' \
	> /etc/apt/sources.list \
	&& apt-get update \
	&& apt-get install -y gcc libpq-dev zlib1g-dev libjpeg62-turbo-dev dpkg-dev
COPY requirements.txt .
RUN pip install --user -r requirements.txt

FROM python:3.6-slim
RUN printf '%s\n' \
	'deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/20260608T000000Z bullseye main' \
	'deb [check-valid-until=no] http://snapshot.debian.org/archive/debian-security/20260608T021553Z bullseye-security main' \
	> /etc/apt/sources.list \
	&& apt-get update \
	&& apt-get install -y --no-install-recommends libpq5 libjpeg62-turbo zlib1g \
	&& rm -rf /var/lib/apt/lists/*
COPY --from=builder /root/.local /root/.local
COPY . .
ENV PATH=/root/.local/bin:$PATH
ENTRYPOINT bash -c "python manage.py migrate data && python telegram.py"