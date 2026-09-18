#!/usr/bin/env bash
# Build the Jekyll site, sync it to S3, and invalidate the CloudFront cache.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

S3_BUCKET="s3://pub.gctl.io"
CLOUDFRONT_DISTRIBUTION_ID="E5OC8E0HGYHMD"

echo "==> Building site"
rm -rf _site
bundle exec jekyll build

echo "==> Syncing to ${S3_BUCKET}"
aws s3 sync _site "${S3_BUCKET}" --delete

echo "==> Invalidating CloudFront distribution ${CLOUDFRONT_DISTRIBUTION_ID}"
aws cloudfront create-invalidation --distribution-id "${CLOUDFRONT_DISTRIBUTION_ID}" --paths "/*"

echo "==> Done"
