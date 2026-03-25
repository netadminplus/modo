# SSL Certificates Directory

Place your SSL certificate files here:

- **fullchain.pem** - Your domain certificate + intermediate CA bundle
- **privkey.pem** - Your private key

## File requirements:

1. `fullchain.pem` - The full certificate chain (domain cert + intermediates)
2. `privkey.pem` - The private key (must match the certificate)

## Example (if using Let's Encrypt manually):

```bash
# After running certbot, copy the files:
sudo cp /etc/letsencrypt/live/modo.netadminplus.ir/fullchain.pem ./fullchain.pem
sudo cp /etc/letsencrypt/live/modo.netadminplus.ir/privkey.pem ./privkey.pem
sudo chmod 644 fullchain.pem
sudo chmod 600 privkey.pem
```

## Permissions:
- `fullchain.pem`: readable (644)
- `privkey.pem`: private (600)
