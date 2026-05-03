import environ

env = environ.FileAwareEnv()

# CloudFront distribution that fronts the wiki. Empty in dev / staging
# without a CDN, in which case `wiki.lib.cloudfront.invalidate_paths`
# becomes a no-op.
CLOUDFRONT_DISTRIBUTION_ID = env("CLOUDFRONT_DISTRIBUTION_ID", default="")
