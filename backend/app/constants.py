# PlaidItem.access_token_ciphertext is a non-nullable column, so this
# can't be None without a schema change -- instead it's a plain string
# that is NOT valid Fernet ciphertext. app.token_encryption.decrypt_token
# (the only code path that ever reads this column) always raises
# TokenEncryptionError on it, so a sync attempt fails at the decryption
# step itself, before any network call to Plaid could happen. This is
# deliberately NOT run through encrypt_token() -- encrypting a fake
# payload would still "pretend" to be a valid stored token; failing to
# decrypt at all is the stronger guarantee. See
# test_demo_plaid_token_is_not_decryptable for proof.
DEMO_PLAID_TOKEN_PLACEHOLDER = "not-a-plaid-token::demo-user-has-no-real-connection"
