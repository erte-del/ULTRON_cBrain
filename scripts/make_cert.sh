#!/bin/bash
# Make Ultron's signing certificate, once. A self-signed one that only exists on this Mac.
#   scripts/make_cert.sh
# Why: Ultron.app signed "ad hoc" gets a new identity every time it is rebuilt, so macOS forgets
# the Screen Recording permission you gave it. Signed with this certificate, the identity stays
# the same across rebuilds. make_app.sh uses it when it exists. Mac only.
set -e

NAME="Ultron Local Signing"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"

if security find-certificate -c "$NAME" "$KEYCHAIN" >/dev/null 2>&1; then
  echo "Already there: $NAME"
  exit 0
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS="ultron-$$"

cat >"$TMP/cert.conf" <<EOF
[req]
distinguished_name = dn
x509_extensions = ext
prompt = no
[dn]
CN = $NAME
[ext]
keyUsage = critical, digitalSignature
extendedKeyUsage = critical, codeSigning
basicConstraints = critical, CA:false
EOF

/usr/bin/openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -config "$TMP/cert.conf" \
  -keyout "$TMP/key.pem" -out "$TMP/cert.pem" 2>/dev/null
/usr/bin/openssl pkcs12 -export -inkey "$TMP/key.pem" -in "$TMP/cert.pem" -out "$TMP/cert.p12" -passout "pass:$PASS"

# -T: let codesign use the key without asking each time.
security import "$TMP/cert.p12" -k "$KEYCHAIN" -P "$PASS" -T /usr/bin/codesign >/dev/null
echo "Made $NAME in your login keychain. Now run scripts/make_app.sh"
