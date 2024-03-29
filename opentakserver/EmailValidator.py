import tldextract
from flask_security import MailUtil
from opentakserver.extensions import logger


class EmailValidator(MailUtil):

    def __init__(self, app):
        super().__init__(app)
        self.app = app

    def validate(self, email: str) -> str:
        domain_whitelist = self.app.config.get("OTS_EMAIL_DOMAIN_WHITELIST")
        domain_blacklist = self.app.config.get("OTS_EMAIL_DOMAIN_BLACKLIST")
        tld_whitelist = self.app.config.get("OTS_EMAIL_TLD_WHITELIST")
        tld_blacklist = self.app.config.get("OTS_EMAIL_TLD_BLACKLIST")

        domain = email.split("@")[-1]
        parsed_domain = tldextract.extract(domain)
        logger.debug("Got domain: {}".format(domain))

        if domain_whitelist and domain not in domain_whitelist:
            logger.error("Domain {} is not whitelisted".format(domain))
            raise ValueError("Domain {} is not whitelisted".format(domain))

        if domain_blacklist and domain in domain_blacklist:
            logger.error("Domain {} is blacklisted".format(domain))
            raise ValueError("Domain {} is blacklisted".format(domain))

        if tld_whitelist and parsed_domain.suffix not in tld_whitelist:
            logger.error("TLD {} not whitelisted".format(parsed_domain.suffix))
            raise ValueError("TLD {} not whitelisted".format(parsed_domain.suffix))

        if tld_blacklist and parsed_domain.suffix in tld_blacklist:
            logger.error("TLD {} is blacklisted".format(parsed_domain.suffix))
            raise ValueError("TLD {} is blacklisted".format(parsed_domain.suffix))

        logger.info("Looks like {} is good".format(email))
        return super().validate(email)
