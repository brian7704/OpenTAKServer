from jinja2 import Template

ca_config = """default_crl_days= 730                   # how long before next CRL

[ ca ]
        default_ca      = CA_default            # The default ca section

[ CA_default ]
        dir             = .                     # Where everything is kept
        certs           = $dir          # Where the issued certs are kept
        crl_dir         = $dir/crl              # Where the issued crl are kept
        database        = $dir/crl_index.txt    # database index file.
        default_md      = default               # use public key default MD

[ req ]
        default_bits           = 2048
        default_keyfile        = ca.pem
        distinguished_name     = req_distinguished_name
        x509_extensions        = v3_ca

[ req_distinguished_name ]
        countryName_min                = 2
        countryName_max                = 2
        commonName_max                 = 64

[ v3_ca ]
#basicConstraints=critical,CA:TRUE, pathlen:2
basicConstraints=critical,CA:TRUE
keyUsage=critical, cRLSign, keyCertSign
#nameConstraints=critical,permitted;DNS:.bbn.com # this allows you to restrict a CA to only issue server certs for a particular domain

[ client ]
basicConstraints=critical,CA:FALSE
keyUsage=critical, digitalSignature, keyEncipherment
extendedKeyUsage = critical, clientAuth
#extendedKeyUsage = critical, clientAuth, challengePassword
#authorityInfoAccess = OCSP;URI: http://localhost:4444

[ server ]
basicConstraints=critical,CA:FALSE
keyUsage=critical, digitalSignature, keyEncipherment
extendedKeyUsage = critical, clientAuth, serverAuth
#authorityInfoAccess = OCSP;URI: http://localhost:4444"""

server_config = Template("""default_crl_days= 730                   # how long before next CRL

[ ca ]
        default_ca      = CA_default            # The default ca section

[ CA_default ]
        dir             = .                     # Where everything is kept
        certs           = $dir          # Where the issued certs are kept
        crl_dir         = $dir/crl              # Where the issued crl are kept
        database        = $dir/crl_index.txt    # database index file.
        default_md      = default               # use public key default MD

[ req ]
        default_bits           = 2048
        default_keyfile        = ca.pem
        distinguished_name     = req_distinguished_name
        x509_extensions        = v3_ca

[ req_distinguished_name ]
        countryName_min                = 2
        countryName_max                = 2
        commonName_max                 = 64

[ v3_ca ]
#basicConstraints=critical,CA:TRUE, pathlen:2
basicConstraints=critical,CA:TRUE
keyUsage=critical, cRLSign, keyCertSign
#nameConstraints=critical,permitted;DNS:.bbn.com # this allows you to restrict a CA to only issue server certs for a particular domain

[ client ]
basicConstraints=critical,CA:FALSE
keyUsage=critical, digitalSignature, keyEncipherment
extendedKeyUsage = critical, clientAuth
#extendedKeyUsage = critical, clientAuth, challengePassword
#authorityInfoAccess = OCSP;URI: http://localhost:4444

[ server ]
basicConstraints=critical,CA:FALSE
keyUsage=critical, digitalSignature, keyEncipherment
extendedKeyUsage = critical, clientAuth, serverAuth
#authorityInfoAccess = OCSP;URI: http://localhost:4444

subjectAltName = @alt_names
[alt_names]
{{ alt_name_field }} = {{ common_name }}
""")