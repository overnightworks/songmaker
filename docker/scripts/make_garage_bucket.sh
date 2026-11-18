#!/bin/sh
# Makes the test store's bucket and a key that may read and write it, and writes the key to a
# credentials file in the shape the AWS SDKs read (AWS_SHARED_CREDENTIALS_FILE). Needs curl.
#   ADMIN_URL=http://garage:3903 ADMIN_TOKEN=... BUCKET=songmaker-test CREDENTIALS_FILE=/path sh make_garage_bucket.sh
set -eu
umask 077
: "${ADMIN_URL:?}" "${ADMIN_TOKEN:?}" "${BUCKET:?}" "${CREDENTIALS_FILE:?}"

deadline=$(($(date +%s) + 60))
until curl --silent --fail --max-time 5 --output /dev/null "$ADMIN_URL/health"; do
  [ "$(date +%s)" -lt "$deadline" ] || { echo "make_garage_bucket: the store was not healthy within 60 seconds" >&2; exit 1; }
  sleep 1
done

# call <path> <json>: prints the answer without whitespace; a failed call stops the script.
call() {
  printf '%s' "$2" | curl --silent --fail --max-time 30 --request POST \
    --header "Authorization: Bearer $ADMIN_TOKEN" --header 'Content-Type: application/json' \
    --data-binary @- "$ADMIN_URL$1" | tr -d ' \n'
}
field() { printf '%s' "$1" | grep -o "\"$2\":\"[^\"]*\"" | head -n 1 | cut -d '"' -f 4; }

bucket=$(field "$(call /v2/CreateBucket "{\"globalAlias\":\"$BUCKET\"}")" id)
key=$(call /v2/CreateKey '{"name":"test"}')
key_id=$(field "$key" accessKeyId)
secret=$(field "$key" secretAccessKey)
call /v2/AllowBucketKey \
  "{\"bucketId\":\"$bucket\",\"accessKeyId\":\"$key_id\",\"permissions\":{\"read\":true,\"write\":true}}" >/dev/null
printf '[default]\naws_access_key_id = %s\naws_secret_access_key = %s\n' "$key_id" "$secret" >"$CREDENTIALS_FILE"
