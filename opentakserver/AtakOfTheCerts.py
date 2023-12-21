import os
import zipfile
from shutil import copyfile, rmtree

from jinja2 import Template
from ownca import CertificateAuthority
from ownca.ownca import *
from ownca.ownca import HostCertificate
from ownca.crypto import keys
from ownca.utils import store_file, validate_hostname
from ownca.crypto.certs import _add_dns_as_subjectaltname, _valid_cert, ca_crl, _add_subjectaltnames_sign_csr, issue_csr
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
import datetime
import uuid
from ownca._constants import (CA_CERT, CA_CERTS_DIR, CA_CRL, CA_CSR, CA_KEY,
                              CA_PUBLIC_KEY, COUNTRY_REGEX, HOSTNAME_REGEX, OIDS)


# Overrides initialize() and issue_cert to remove the restriction on max_days
class AtakOfTheCerts(CertificateAuthority):
    def __init__(self, logger=None, pwd=None, *args, **kwargs):
        super().__init__(**kwargs)
        self.logger = logger
        self.pwd = pwd

    def initialize(
            self,
            common_name=None,
            dns_names=None,
            intermediate=False,
            maximum_days=825,
            public_exponent=65537,
            key_size=2048,
    ):
        """
        Initialize the Certificate Authority (CA)

        :param common_name: CA Common Name (CN)
        :type common_name: str, required
        :param dns_names: List of DNS names
        :type dns_names: list of strings, optional
        :param maximum_days: Certificate maximum days duration
        :type maximum_days: int, default: 825
        :param public_exponent: Public Exponent
        :type public_exponent: int, default: 65537
        :param intermediate: Intermediate Certificate Authority mode
        :type intermediate: bool, default False
        :param key_size: Key size
        :type key_size: int, default: 2048

        :return: tuple with CA certificate, CA Key and CA Public key
        :rtype: tuple (
            ``cryptography.x509.Certificate``,
            ``cryptography.hazmat.backends.openssl.rsa``,
            string public key
            )
        """

        private_ca_key_file = os.path.join(self.ca_storage, CA_KEY)
        public_ca_key_file = os.path.join(self.ca_storage, CA_PUBLIC_KEY)
        certificate_file = os.path.join(self.ca_storage, CA_CERT)
        csr_file = os.path.join(self.ca_storage, CA_CSR)
        crl_file = os.path.join(self.ca_storage, CA_CRL)

        if self.current_ca_status is True:
            cert_data = load_cert_files(
                common_name=common_name,
                key_file=private_ca_key_file,
                public_key_file=public_ca_key_file,
                csr_file=csr_file,
                certificate_file=certificate_file,
                crl_file=crl_file,
            )

            return cert_data

        elif self.current_ca_status is False:
            raise OwnCAInvalidFiles(self.status)

        elif self.current_ca_status is None:
            key = keys.generate(
                public_exponent=public_exponent, key_size=key_size
            )

            store_file(key.key_bytes, private_ca_key_file, False, None)
            store_file(key.public_key_bytes, public_ca_key_file, False, None)

            if intermediate is True:
                csr = issue_csr(
                    key=key.key,
                    common_name=common_name,
                    dns_names=dns_names,
                    oids=self.oids,
                )
                csr_bytes = csr.public_bytes(
                    encoding=serialization.Encoding.PEM
                )

                store_file(csr_bytes, csr_file, False, None)

                cert_data = OwncaCertData(
                    {
                        "cert": None,
                        "cert_bytes": None,
                        "csr": csr,
                        "csr_bytes": csr_bytes,
                        "key": key.key,
                        "key_bytes": key.key_bytes,
                        "public_key": key.public_key,
                        "public_key_bytes": key.public_key_bytes,
                        "crl": None,
                        "crl_bytes": None,
                    }
                )

                return cert_data

            certificate = self.issue_cert(
                self.oids,
                maximum_days=maximum_days,
                key=key.key,
                pem_public_key=key.public_key,
                common_name=common_name,
                dns_names=dns_names,
            )

            if not certificate:
                raise OwnCAFatalError(self.status)

            else:
                crl = ca_crl(
                    certificate,
                    ca_key=key.key,
                    common_name=common_name,
                )

                crl_bytes = crl.public_bytes(
                    encoding=serialization.Encoding.PEM
                )

                store_file(crl_bytes, crl_file, False, None)

                certificate_bytes = certificate.public_bytes(
                    encoding=serialization.Encoding.PEM
                )

                store_file(certificate_bytes, certificate_file, False, None)

                cert_data = OwncaCertData(
                    {
                        "cert": certificate,
                        "cert_bytes": certificate_bytes,
                        "key": key.key,
                        "key_bytes": key.key_bytes,
                        "public_key": key.public_key,
                        "public_key_bytes": key.public_key_bytes,
                        "crl": crl,
                        "crl_bytes": crl_bytes,
                    }
                )

                self._common_name = common_name
                self._update(cert_data)

                return cert_data

    def pem_to_p12(self, p12_file, subject_key, subject_certificate):
        ca_private_key = serialization.load_pem_private_key(self.key_bytes, None, default_backend())

        p12 = pkcs12.serialize_key_and_certificates(
            key=subject_key.key, cert=subject_certificate,
            name='certbundle'.encode(), cas=[self.cert],
            encryption_algorithm=serialization.BestAvailableEncryption(self.pwd.encode()))

        p12_file = open(p12_file, 'wb')
        p12_file.write(p12)
        p12_file.close()

    def issue_certificate(
            self,
            hostname,
            common_name,
            maximum_days=825,
            dns_names=None,
            oids=None,
            public_exponent=65537,
            key_size=2048,
            ca=True,
            cert_password=None
    ):
        """
        Issues a new certificate signed by the CA

        :param hostname: Hostname
        :type hostname: str, required
        :param maximum_days: Certificate maximum days duration
        :type maximum_days: int, default: 825
        :param common_name: Common Name (CN) when loading existent certificate
        :type common_name: str, optional
        :param dns_names: List of DNS names
        :type dns_names: list of strings, optional
        :param oids: CA Object Identifiers (OIDs). The are typically seen
            in X.509 names.
            Allowed keys/values:
            ``'country_name': str (two letters)``,
            ``'locality_name': str``,
            ``'state_or_province': str``,
            ``'street_address': str``,
            ``'organization_name': str``,
            ``'organization_unit_name': str``,
            ``'email_address': str``,
        :type oids: dict, optional, all keys are optional
        :param public_exponent: Public Exponent
        :type public_exponent: int, default: 65537
        :param key_size: Key size
        :type key_size: int, default: 2048
        :param ca: Certificate is CA or not.
        :type ca: bool, default True.

        :return: host object
        :rtype: ``ownca.ownca.HostCertificate``
        """
        if not validate_hostname(hostname):
            raise TypeError(
                "Invalid 'hostname'. Hostname must to be a string following "
                + f"the hostname rules r'{HOSTNAME_REGEX}'"
            )

        host_cert_dir = os.path.join(self.ca_storage, CA_CERTS_DIR, common_name)
        host_key_path = os.path.join(host_cert_dir, f"{common_name}.pem")
        host_public_path = os.path.join(host_cert_dir, f"{common_name}.pub")
        host_csr_path = os.path.join(host_cert_dir, f"{common_name}.csr")
        host_cert_path = os.path.join(host_cert_dir, f"{common_name}.crt")
        p12_path = os.path.join(host_cert_dir, f"{common_name}.p12")
        crl_file = os.path.join(self.ca_storage, CA_CRL)

        files = {
            "certificate": host_cert_path,
            "key": host_key_path,
            "public_key": host_public_path,
            "p12": p12_path
        }

        self.logger.info("Doing cert for {}".format(common_name))

        if os.path.isdir(host_cert_dir):
            self.logger.info("loading cert {} {}".format(host_cert_dir, host_public_path))
            cert_data = load_cert_files(
                common_name=common_name,
                key_file=host_key_path,
                public_key_file=host_public_path,
                csr_file=host_csr_path,
                certificate_file=host_cert_path,
                crl_file=crl_file,
            )

        else:
            self.logger.info("making dirs {}".format(host_cert_dir))
            os.mkdir(host_cert_dir)
            key_data = keys.generate(
                public_exponent=public_exponent, key_size=key_size
            )

            store_file(key_data.key_bytes, host_key_path, False, 0o600)
            store_file(
                key_data.public_key_bytes, host_public_path, False, None
            )

            if oids:
                oids = format_oids(oids)

            else:
                oids = list()

            csr = issue_csr(
                key=key_data.key,
                common_name=common_name,
                dns_names=dns_names,
                oids=oids,
                ca=ca,
            )

            store_file(
                csr.public_bytes(encoding=serialization.Encoding.PEM),
                host_csr_path,
                False,
                None,
            )

            certificate = self.ca_sign_csr(
                self.cert,
                self.key,
                csr,
                key_data.public_key,
                maximum_days=maximum_days,
                ca=ca,
            )
            certificate_bytes = certificate.public_bytes(
                encoding=serialization.Encoding.PEM
            )

            store_file(certificate_bytes, host_cert_path, False, None)

            self.pem_to_p12(p12_path, key_data, certificate)

            cert_data = OwncaCertData(
                {
                    "cert": certificate,
                    "cert_bytes": certificate_bytes,
                    "key": key_data.key,
                    "key_bytes": key_data.key_bytes,
                    "public_key": key_data.public_key,
                    "public_key_bytes": key_data.public_key_bytes,
                    "crl": self.crl,
                    "crl_bytes": self.crl_bytes,
                }
            )

        host = HostCertificate(common_name, files, cert_data)

        return host

    def issue_cert(
            self,
            oids,
            maximum_days=None,
            key=None,
            pem_public_key=None,
            ca_common_name=None,
            common_name=None,
            dns_names=None,
            host=False,
            ca=True,
    ):
        """
        Issue a new certificate

        :param oids: list of OID Objects (``cryptography.x509.oid.NameOID``)
            or None. See ``ownca.format_oids``.
        :type oids: list, required.
        :param maximum_days: number of maximum days of certificate (expiration)
        :type maximum_days: int, required, min 1 max 825.
        :param key: key object ``cryptography.hazmat.backends.openssl.rsa``
        :type key: object, required.
        :param pem_public_key: PEM public key object
            ``cryptography.hazmat.backends.openssl.rsa.public_key()``.
        :type pem_public_key: object, required.
        :param ca_common_name: Certificate Authority Common Name when issuing cert.
        :type ca_common_name: string, optional.
        :param common_name: Common Name when issuing Certificate Authority cert.
        :type common_name: string, optional.
        :param dns_names: list of DNS names to the cert.
        :type dns_names: list of strings.
        :param host: Issuing a host certificate.
        :type host: bool, default True.
        :param ca: Certificate is CA or not.
        :type ca: bool, default True.

        :return: certificate object
        :rtype: ``cryptography.x509.Certificate``
        """

        oids.append(x509.NameAttribute(NameOID.COMMON_NAME, common_name))

        builder = x509.CertificateBuilder()

        builder = builder.subject_name(x509.Name(oids))

        if host:
            builder = builder.issuer_name(
                x509.Name(
                    [x509.NameAttribute(NameOID.COMMON_NAME, ca_common_name)]
                )
            )

            builder = _add_dns_as_subjectaltname(
                builder, ca_common_name, dns_names
            )

        else:

            builder = builder.issuer_name(
                x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
            )

            builder = _add_dns_as_subjectaltname(builder, common_name, dns_names)

        one_day = datetime.timedelta(1, 0, 0)
        builder = builder.not_valid_before(datetime.datetime.today() - one_day)
        builder = builder.not_valid_after(
            datetime.datetime.today() + (one_day * maximum_days)
        )
        builder = builder.serial_number(x509.random_serial_number())
        builder = builder.public_key(pem_public_key)

        builder = builder.add_extension(
            x509.BasicConstraints(ca=ca, path_length=None), critical=True
        )

        certificate = builder.sign(
            private_key=key, algorithm=hashes.SHA256(), backend=default_backend()
        )

        return _valid_cert(certificate)

    def ca_sign_csr(self, ca_cert, ca_key, csr, public_key, maximum_days=None, ca=True, common_name=''):
        """
        Sign a Certificate Signing Request

        :param ca_cert: CA certificate object ``cryptography.x509.Certificate``
        :type ca_cert: object, required.
        :param ca_key: CA key object ``cryptography.hazmat.backends.openssl.rsa``
        :type ca_key: object, required.
        :param csr: CSR object ``cryptography.x509.CertificateSigningRequest``
        :type csr: object, required.
        :param key: key object ``cryptography.hazmat.backends.openssl.rsa``
        :param maximum_days: number of maximum days of certificate (expiration)
        :type maximum_days: int, required, min 1 max 825.
        :param ca: Certificate is CA or not.
        :type ca: bool, default True.

        :return: certificate object
        :rtype: ``cryptography.x509.Certificate``
        :raises: ``ValueError``
        """

        one_day = datetime.timedelta(1, 0, 0)

        certificate = x509.CertificateBuilder()
        certificate = certificate.subject_name(csr.subject)
        certificate = _add_subjectaltnames_sign_csr(certificate, csr)
        certificate = certificate.issuer_name(ca_cert.subject)
        certificate = certificate.public_key(csr.public_key())
        certificate = certificate.serial_number(uuid.uuid4().int)
        certificate = certificate.add_extension(x509.SubjectKeyIdentifier.from_public_key(csr.public_key()),
                                                critical=False)
        # certificate = certificate.add_extension(x509.SubjectAlternativeName([x509.DNSName(common_name)]), critical=False)
        certificate = certificate.not_valid_before(
            datetime.datetime.today() - one_day
        )
        certificate = certificate.not_valid_after(
            datetime.datetime.today() + (one_day * maximum_days)
        )
        certificate = certificate.add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=True,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
                key_cert_sign=False,
                crl_sign=False,
            ),
            critical=True,
        )
        certificate = certificate.add_extension(
            x509.BasicConstraints(ca=ca, path_length=None),
            critical=True,
        )
        certificate = certificate.add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(
                public_key
            ),
            critical=False,
        )
        certificate = certificate.sign(
            private_key=ca_key,
            algorithm=hashes.SHA256(),
            backend=default_backend(),
        )

        return _valid_cert(certificate)

    def generate_zip(self, server_address: str = None, server_filename: str = "truststore.p12",
                     user_filename: str = "user.p12",
                     cert_password: str = "atakatak", ssl_port: str = "8089") -> str:
        """
        A Function to generate a Client connection Data Package (DP) from a server and user p12 file in the current
        working directory.
        :param server_address: A string based ip address or FQDN that clients will use to connect to the server
        :param server_filename: The filename of the server p12 file default is truststore.p12
        :param user_filename: The filename of the server p12 file default is user.p12
        :param cert_password: The password for the certificate files
        :param ssl_port: The port used for SSL CoT, defaults to 8089
        """

        server_file_path, server_filename = os.path.split(server_filename)
        user_file_path, user_filename = os.path.split(user_filename)

        pref_file_template = Template("""<?xml version='1.0' standalone='yes'?>
        <preferences>
            <preference version="1" name="cot_streams">
                <entry key="count" class="class java.lang.Integer">1</entry>
                <entry key="description0" class="class java.lang.String">OpenTAKServer_{{ server }}</entry>
                <entry key="enabled0" class="class java.lang.Boolean">true</entry>
                <entry key="connectString0" class="class java.lang.String">{{ server }}:{{ ssl_port }}:ssl</entry>
            </preference>
            <preference version="1" name="com.atakmap.app_preferences">
                <entry key="displayServerConnectionWidget" class="class java.lang.Boolean">true</entry>
                <entry key="caLocation" class="class java.lang.String">/storage/emulated/0/atak/cert/{{ server_filename }}</entry>
                <entry key="caPassword" class="class java.lang.String">{{ cert_password }}</entry>
                <entry key="clientPassword" class="class java.lang.String">{{ cert_password }}</entry>
                <entry key="certificateLocation" class="class java.lang.String">/storage/emulated/0/atak/cert/{{ user_filename }}</entry>
            </preference>
        </preferences>
        """)

        manifest_file_template = Template("""<MissionPackageManifest version="2">
           <Configuration>
              <Parameter name="uid" value="{{ uid }}"/>
              <Parameter name="name" value="OpenTAKServer_{{ server }}"/>
              <Parameter name="onReceiveDelete" value="true"/>
           </Configuration>
           <Contents>
              <Content ignore="false" zipEntry="{{ folder }}/preference.pref"/>
              <Content ignore="false" zipEntry="{{ folder }}/{{ server_filename }}"/>
              <Content ignore="false" zipEntry="{{ folder }}/{{ user_filename }}"/>	  
           </Contents>
        </MissionPackageManifest>
        """)

        manifest_file_parent_template = Template("""<MissionPackageManifest version="2">
               <Configuration>
                  <Parameter name="uid" value="{{ uid }}"/>
                  <Parameter name="name" value="OpenTAKServer_{{ server }}_DP"/>
               </Configuration>
               <Contents>
                  <Content ignore="false" zipEntry="{{ folder }}/{{ internal_dp_name }}.zip"/>
               </Contents>
            </MissionPackageManifest>
            """)

        username = user_filename[:-4]
        random_id = uuid.uuid4()
        new_uid = uuid.uuid4()
        parent_folder = "80b828699e074a239066d454a76284eb"
        folder = "5c2bfcae3d98c9f4d262172df99ebac5"

        pref = pref_file_template.render(server=server_address, server_filename=server_filename,
                                         user_filename=user_filename, cert_password=cert_password,
                                         ssl_port=ssl_port)
        man = manifest_file_template.render(uid=random_id, server=server_address,
                                            server_filename=server_filename,
                                            user_filename=user_filename, folder=folder)
        man_parent = manifest_file_parent_template.render(uid=new_uid, server=server_address,
                                                          folder=parent_folder,
                                                          internal_dp_name=f"{username}")
        if not os.path.exists(os.path.join(user_file_path, folder)):
            os.makedirs(os.path.join(user_file_path, folder))

        if not os.path.exists(os.path.join(user_file_path, 'MANIFEST')):
            os.makedirs(os.path.join(user_file_path, 'MANIFEST'))

        with open(os.path.join(user_file_path, folder, 'preference.pref'), 'w') as pref_file:
            pref_file.write(pref)

        with open(os.path.join(user_file_path, 'MANIFEST', 'manifest.xml'), 'w') as manifest_file:
            manifest_file.write(man)

        self.logger.info("Generating inner Data Package: {}.zip".format(username))

        copyfile(os.path.join(server_file_path, server_filename),
                 os.path.join(user_file_path, folder, server_filename))
        self.logger.info("Copying {} to {}".format(os.path.join(user_file_path, user_filename),
                                                   os.path.join(user_file_path, folder, user_filename)))
        copyfile(os.path.join(user_file_path, user_filename), os.path.join(user_file_path, folder, user_filename))
        zipf = zipfile.ZipFile(os.path.join(user_file_path, "{}.zip".format(username)), 'w', zipfile.ZIP_DEFLATED)

        os.chdir(os.path.join(user_file_path))

        for root, dirs, files in os.walk(folder):
            for file in files:
                zipf.write(os.path.join(root, file))
        for root, dirs, files in os.walk('MANIFEST'):
            for file in files:
                self.logger.debug("adding {} to zip".format(os.path.join(root, file)))
                zipf.write(os.path.join(root, file))
        zipf.close()

        rmtree(os.path.join(user_file_path, "MANIFEST"))
        rmtree(os.path.join(user_file_path, folder))

        # Create outer DP...because WinTAK
        if not os.path.exists(os.path.join(user_file_path, parent_folder)):
            os.makedirs(os.path.join(user_file_path, parent_folder))
        if not os.path.exists(os.path.join(user_file_path, "MANIFEST")):
            os.makedirs(os.path.join(user_file_path, "MANIFEST"))
        with open(os.path.join(user_file_path, "MANIFEST", 'manifest.xml'), 'w') as manifest_parent:
            manifest_parent.write(man_parent)

        self.logger.info("Generating Main Data Package: {}_DP.zip".format(username))
        copyfile(os.path.join(user_file_path, "{}.zip".format(username)), os.path.join(user_file_path, parent_folder,
                                                                                       "{}.zip".format(username)))
        zipp = zipfile.ZipFile(os.path.join(user_file_path, "{}_DP.zip".format(username)), 'w', zipfile.ZIP_DEFLATED)

        for root, dirs, files in os.walk(parent_folder):
            for file in files:
                zipp.write(os.path.join(root, file))
        for root, dirs, files in os.walk('MANIFEST'):
            for file in files:
                zipp.write(os.path.join(root, file))
        zipp.close()

        rmtree(os.path.join(user_file_path, "MANIFEST"))
        rmtree(os.path.join(user_file_path, parent_folder))
        os.remove(os.path.join(user_file_path, "{}.zip".format(username)))

        return "{}_DP.zip".format(username)
