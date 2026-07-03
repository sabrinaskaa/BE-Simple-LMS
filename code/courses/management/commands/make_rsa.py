from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Generate RSA private/public key pair for JWT RS256 signing."

    def add_arguments(self, parser):
        parser.add_argument("--private", default=getattr(settings, "JWT_PRIVATE_KEY_PATH", ""), help="Path output private key PEM")
        parser.add_argument("--public", default=getattr(settings, "JWT_PUBLIC_KEY_PATH", ""), help="Path output public key PEM")
        parser.add_argument("--bits", type=int, default=2048, help="RSA key size")

    def handle(self, *args, **options):
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
        except ImportError as exc:
            raise SystemExit("Package cryptography belum terinstall. Jalankan: pip install cryptography") from exc

        private_path = Path(options["private"])
        public_path = Path(options["public"])
        private_path.parent.mkdir(parents=True, exist_ok=True)
        public_path.parent.mkdir(parents=True, exist_ok=True)

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=options["bits"])
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        private_path.write_bytes(private_pem)
        public_path.write_bytes(public_pem)
        self.stdout.write(self.style.SUCCESS(f"RSA private key dibuat: {private_path}"))
        self.stdout.write(self.style.SUCCESS(f"RSA public key dibuat : {public_path}"))
        self.stdout.write("Set JWT_ALGORITHM=RS256 untuk memakai key ini.")
