import os
import random
import re
import subprocess
import uuid
import zipfile
from pathlib import Path
from shutil import copyfile, rmtree
from jinja2 import Template


class CertificateAuthority:

    def __init__(self, logger, app):
        self.logger = logger
        self.app = app

    def create_ca(self):
        if not self.check_if_ca_exists():
            self.logger.info("Creating CA...")
            os.makedirs(self.app.config.get("OTS_CA_FOLDER"), exist_ok=True)

            copyfile(os.path.join("opentakserver", "ca_config.cfg"),
                     os.path.join(self.app.config.get("OTS_CA_FOLDER"), "ca_config.cfg"))

            subject = self.app.config.get("OTS_CA_SUBJECT") + "/CN={}".format(self.app.config.get("OTS_CA_NAME"))

            command = (
                'openssl req -new -sha256 -x509 -days {} -extensions v3_ca -keyout {} -out {} -passout pass:{} -config {} -subj {}'
                .format(self.app.config.get("OTS_CA_EXPIRATION_TIME"),
                        os.path.join(self.app.config.get("OTS_CA_FOLDER"), "ca-do-not-share.key"),
                        os.path.join(self.app.config.get("OTS_CA_FOLDER"), "ca.pem"),
                        self.app.config.get("OTS_CA_PASSWORD"),
                        os.path.join(self.app.config.get("OTS_CA_FOLDER"), "ca_config.cfg"),
                        subject))

            self.logger.debug(command)

            exit_code = subprocess.call(command, shell=True)

            if exit_code:
                raise Exception("Failed to create ca.pem. Exit code {}".format(exit_code))

            # os.chmod(os.path.join(self.app.config.get("OTS_CA_FOLDER"), "ca-do-not-share.key"), 1411)

            command = ('openssl x509 -in {} -addtrust clientAuth -addtrust serverAuth -setalias {} -out {}'
                       .format(os.path.join(self.app.config.get("OTS_CA_FOLDER"), "ca.pem"),
                               self.app.config.get("OTS_CA_NAME"),
                               os.path.join(self.app.config.get("OTS_CA_FOLDER"), "ca-trusted.pem")))

            self.logger.debug(command)

            exit_code = subprocess.call(command, shell=True)

            if exit_code:
                raise Exception("Failed to add trust to CA. Exit code {}".format(exit_code))

            command = ('openssl pkcs12 -legacy -export -in {} -out {} -passout pass:{} -nokeys -caname {}'
                       .format(os.path.join(self.app.config.get("OTS_CA_FOLDER"), "ca-trusted.pem"),
                               os.path.join(self.app.config.get("OTS_CA_FOLDER"), "truststore-root.p12"),
                               self.app.config.get("OTS_CA_PASSWORD"),
                               self.app.config.get("OTS_CA_NAME")))

            self.logger.debug(command)

            exit_code = subprocess.call(command, shell=True)

            if exit_code:
                raise Exception("Failed to export truststore. Exit code {}".format(exit_code))

            command = (
                'keytool -import -trustcacerts -file {} -keystore truststore-root.jks -alias {} -storepass {} -noprompt'
                .format(os.path.join(self.app.config.get("OTS_CA_FOLDER"), "ca.pem"),
                        self.app.config.get("OTS_CA_NAME"),
                        self.app.config.get("OTS_CA_PASSWORD")))

            self.logger.debug(command)

            exit_code = subprocess.call(command, shell=True)

            if exit_code != 0 and exit_code != 1:
                raise Exception("Failed to import trustcacerts. Exit code {}".format(exit_code))

            Path(os.path.join(self.app.config.get("OTS_CA_FOLDER"), "crl_index.txt")).touch()
            f = open(os.path.join(self.app.config.get("OTS_CA_FOLDER"), "crl_index.txt.attr"), 'w')
            f.write("unique_subject = no")
            f.close()

            command = ('cd {} && openssl ca -config {} -gencrl -keyfile {} -passin pass:{} -cert {} -out {}'
                       .format(self.app.config.get("OTS_CA_FOLDER"),
                               os.path.join(self.app.config.get("OTS_CA_FOLDER"), "ca_config.cfg"),
                               os.path.join(self.app.config.get("OTS_CA_FOLDER"), 'ca-do-not-share.key'),
                               self.app.config.get("OTS_CA_PASSWORD"),
                               os.path.join(self.app.config.get("OTS_CA_FOLDER"), "ca.pem"),
                               os.path.join(self.app.config.get("OTS_CA_FOLDER"), "ca.crl")))

            self.logger.debug(command)

            exit_code = subprocess.call(command, shell=True)

            if exit_code:
                raise Exception("Failed to create crl. Exit code {}".format(exit_code))

            self.logger.debug("Creating server cert...")
            self.issue_certificate(self.app.config.get("OTS_SERVER_ADDRESS"), True)

        else:
            self.logger.debug("CA already exists")

    def issue_certificate(self, common_name, server=False):
        if not os.path.exists(os.path.join(self.app.config.get("OTS_CA_FOLDER"), "ca.pem")):
            raise FileNotFoundError("ca.pem not found")

        if os.path.exists(os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", common_name)):
            raise Exception("There is already a certificate for {}".format(common_name))

        os.makedirs(os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", common_name))

        subject = self.app.config.get("OTS_CA_SUBJECT") + "/CN={}".format(common_name)

        command = (
            'openssl req -new -newkey rsa:2048 -sha256 -keyout {} -passout pass:{} -out {} -subj {}'
            .format(os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", common_name, common_name + ".key"),
                    self.app.config.get("OTS_CA_PASSWORD"),
                    os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", common_name, common_name + ".csr"),
                    subject))

        self.logger.debug(command)

        exit_code = subprocess.call(command, shell=True)
        if exit_code:
            raise Exception("Failed to create csr. Exit code {}".format(exit_code))

        csr = open(os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", common_name, common_name + ".csr"), 'r')
        csr_bytes = csr.read().encode()
        csr.close()

        self.sign_csr(csr_bytes, common_name, server)

        command = (
            'openssl pkcs12 -legacy -export -in {}.pem -inkey {}.key -out {}.p12 -name {} -CAfile {} -passin pass:{} -passout pass:{}'
            .format(os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", common_name, common_name),
                    os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", common_name, common_name),
                    os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", common_name, common_name),
                    common_name,
                    os.path.join(self.app.config.get("OTS_CA_FOLDER"), "ca.pem"),
                    self.app.config.get("OTS_CA_PASSWORD"),
                    self.app.config.get("OTS_CA_PASSWORD")))

        self.logger.debug(command)

        exit_code = subprocess.call(command, shell=True)
        if exit_code:
            raise Exception("Failed to export p12 key. Exit code {}".format(exit_code))

        command = (
            'keytool -importkeystore -deststorepass {} -destkeypass {} -destkeystore {}.jks -srckeystore {}.p12 -srcstoretype PKCS12 -srcstorepass {} -alias {}'
            .format(self.app.config.get("OTS_CA_PASSWORD"),
                    self.app.config.get("OTS_CA_PASSWORD"),
                    os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", common_name, common_name),
                    os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", common_name, common_name),
                    self.app.config.get("OTS_CA_PASSWORD"),
                    common_name))

        self.logger.debug(command)

        exit_code = subprocess.call(command, shell=True)
        if exit_code:
            raise Exception("Failed to import key. Exit code {}".format(exit_code))

        os.chmod(os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", common_name, common_name + ".key"), 620)

        command = 'openssl rsa -in {} -passin pass:{} -out {}'.format(
            os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", common_name, common_name + ".key"),
            os.path.join(self.app.config.get("OTS_CA_PASSWORD")),
            os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", common_name, common_name + '.nopass.key'))

        self.logger.debug(command)

        exit_code = subprocess.call(command, shell=True)
        if exit_code:
            raise Exception("Failed to remove server key password. Exit code {}".format(exit_code))

        return self.generate_zip(common_name)

    def sign_csr(self, csr_bytes, common_name, server=False):
        os.makedirs(os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", common_name), exist_ok=True)
        f = open(os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", common_name, common_name + ".csr"), 'wb')
        f.write(csr_bytes)
        f.close()

        if server:
            if re.match("^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$", common_name):
                alt_name_field = "IP.1"
            else:
                alt_name_field = "DNS.1"

            copyfile(os.path.join(self.app.config.get("OTS_CA_FOLDER"), "ca_config.cfg"),
                     os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", common_name,
                                  "{}_config.cfg".format(common_name)))

            f = open(os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", common_name,
                                  "{}_config.cfg".format(common_name)), 'a')
            f.write("\nsubjectAltName = @alt_names\n")
            f.write("\n[alt_names]\n")
            f.write("\n{} = {}\n".format(alt_name_field, common_name))
            f.close()

            config_file = os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", common_name,
                                       "{}_config.cfg".format(common_name))
            extensions = 'server'
        else:
            config_file = os.path.join(self.app.config.get("OTS_CA_FOLDER"), "ca_config.cfg")
            extensions = 'client'

        command = (
            'openssl x509 -sha256 -req -days {} -in {} -CA {} -CAkey {} -out {} -set_serial {} -passin pass:{} -extensions {} -extfile {}'
            .format(self.app.config.get("OTS_CA_EXPIRATION_TIME"),
                    os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", common_name, common_name + ".csr"),
                    os.path.join(self.app.config.get("OTS_CA_FOLDER"), "ca.pem"),
                    os.path.join(self.app.config.get("OTS_CA_FOLDER"), "ca-do-not-share.key"),
                    os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", common_name, common_name + ".pem"),
                    random.randint(10000, 100000),
                    self.app.config.get("OTS_CA_PASSWORD"),
                    extensions,
                    config_file))

        self.logger.debug(command)

        exit_code = subprocess.call(command, shell=True)
        if exit_code:
            raise Exception("Failed to sign csr. Exit code {}".format(exit_code))

        f = open(os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", common_name, common_name + ".pem"), 'r')
        cert_bytes = f.read().encode()
        f.close()

        return cert_bytes

    def check_if_ca_exists(self):
        return os.path.exists(os.path.join(self.app.config.get("OTS_CA_FOLDER"), 'ca.pem'))

    def generate_zip(self, common_name):
        truststore = os.path.join(self.app.config.get("OTS_CA_FOLDER"), 'truststore-root.p12')
        user_p12 = os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", common_name,
                                "{}.p12".format(common_name))
        user_file_path = os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", common_name)
        random_id = uuid.uuid4()
        new_uid = uuid.uuid4()
        parent_folder = "80b828699e074a239066d454a76284eb"
        folder = "5c2bfcae3d98c9f4d262172df99ebac5"

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

        pref = pref_file_template.render(server=self.app.config.get("OTS_SERVER_ADDRESS"),
                                         server_filename=truststore,
                                         user_filename=user_p12,
                                         cert_password=self.app.config.get("OTS_CA_PASSWORD"),
                                         ssl_port=self.app.config.get("OTS_SSL_STREAMING_PORT"))
        man = manifest_file_template.render(uid=random_id, server=self.app.config.get("OTS_SERVER_ADDRESS"),
                                            server_filename=truststore,
                                            user_filename=user_p12, folder=folder)
        man_parent = manifest_file_parent_template.render(uid=new_uid, server=self.app.config.get("OTS_SERVER_ADDRESS"),
                                                          folder=parent_folder,
                                                          internal_dp_name=common_name)

        if not os.path.exists(os.path.join(user_file_path, folder)):
            os.makedirs(os.path.join(user_file_path, folder))

        if not os.path.exists(os.path.join(user_file_path, 'MANIFEST')):
            os.makedirs(os.path.join(user_file_path, 'MANIFEST'))

        with open(os.path.join(user_file_path, folder, 'preference.pref'), 'w') as pref_file:
            pref_file.write(pref)

        with open(os.path.join(user_file_path, 'MANIFEST', 'manifest.xml'), 'w') as manifest_file:
            manifest_file.write(man)

        self.logger.debug("Generating inner Data Package: {}.zip".format(common_name))

        copyfile(truststore, os.path.join(user_file_path, folder, "truststore-root.p12"))
        self.logger.debug("Copying {} to {}".format(truststore, os.path.join(user_file_path, folder,
                                                                             "truststore-root.p12")))
        copyfile(user_p12, os.path.join(user_file_path, folder, "{}.p12".format(common_name)))
        zipf = zipfile.ZipFile(os.path.join(user_file_path, "{}.zip".format(common_name)), 'w', zipfile.ZIP_DEFLATED)

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

        self.logger.info("Generating Main Data Package: {}_DP.zip".format(common_name))
        copyfile(os.path.join(user_file_path, "{}.zip".format(common_name)), os.path.join(user_file_path, parent_folder,
                                                                                          "{}.zip".format(common_name)))
        zipp = zipfile.ZipFile(os.path.join(user_file_path, "{}_DP.zip".format(common_name)), 'w', zipfile.ZIP_DEFLATED)

        for root, dirs, files in os.walk(parent_folder):
            for file in files:
                zipp.write(os.path.join(root, file))
        for root, dirs, files in os.walk('MANIFEST'):
            for file in files:
                zipp.write(os.path.join(root, file))
        zipp.close()

        rmtree(os.path.join(user_file_path, "MANIFEST"))
        rmtree(os.path.join(user_file_path, parent_folder))
        os.remove(os.path.join(user_file_path, "{}.zip".format(common_name)))

        return "{}_DP.zip".format(common_name)
