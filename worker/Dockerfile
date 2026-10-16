# The fetch relay (deno-relay.ts) as a container, for Google Cloud Run in a
# European region. CSDD (www.csdd.lv, the Latvia source) answers only European
# IP addresses; GitHub's runners, Cloudflare and Deno Deploy reach it from the
# US and time out. Deploy and secrets: docs/architecture/58-source-latvia.md §7.
#
#   gcloud run deploy csdd-relay --source worker --region europe-north1 \
#     --port 8000 --allow-unauthenticated --set-env-vars RELAY_TOKEN=...
FROM denoland/deno:2.1.4
WORKDIR /app
COPY deno-relay.ts .
USER deno
EXPOSE 8000
CMD ["run", "--allow-net", "--allow-env", "deno-relay.ts"]
