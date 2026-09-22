# CreditLens Alternative-Data Underwriting Consent Agreement

**Version:** v1  
**Effective Date:** 2026-09-01  

By submitting this application, you ("the Applicant") provide explicit and informed consent to CreditLens ("we", "us", or "our") to collect, process, and retain your data strictly in accordance with the following terms:

### 1. Purpose Limitation
Your data will be used **solely and exclusively** to assess your creditworthiness, verify your identity, and evaluate eligibility for an unsecured credit line under this specific application. Your data will never be sold, leased, used for marketing or commercial profiling, or repurposed for any secondary objective without your express prior consent.

### 2. Data Collected & Used
To evaluate your application without relying on traditional credit bureau files, we process:
- **KYC Information:** Full legal name, mobile phone number, Permanent Account Number (PAN), Aadhaar number, declared residential address, and stated vocation.
- **Alternative-Data Documents:** Submitted digital documents, including gig-platform earnings screenshots, utility bills, and bank/UPI transaction statements.
- **Extracted Financial & Operational Signals:** Tenure on gig platforms, weekly income consistency, utility payment timeliness, and account cash-flow metrics.

### 3. Non-Identifying Data Retained for Fraud Prevention
To protect against syndicate fraud, identity theft, and duplicate document submissions, we compute and retain non-identifying cryptographic fingerprints:
- **Document Hashes:** Perceptual image hashes (pHash) and cryptographic digests (SHA-256) of submitted documents.
- **Underwriting Precedent Vectors:** Anonymized mathematical vector representations of verified cash-flow metrics.

*These non-identifying hashes cannot be reversed or used to reconstruct your original documents or personal identity, and are permanently dissociated from your personal identifiers upon data purging.*

### 4. Data Retention & Erasure
Your personal KYC data and raw uploaded document files will be retained only for as long as necessary to complete underwriting and fulfill regulatory obligations:
- **Standard Retention:** Raw documents and identifiable KYC data are retained for **90 days** from the date of submission, after which document files are permanently deleted and personal identifiers are irreversibly redacted.
- **Anonymized Records:** Fully anonymized decision records (score, decision tier, reason codes) and append-only cryptographic audit trail entries are retained for regulatory compliance and model validation.

### 5. Right to Withdraw Consent
You have the unconditional right to withdraw your consent at any time:
- **How to Withdraw:** You or your authorized underwriter may withdraw consent through the CreditLens portal or by contacting privacy@creditlens.demo.
- **Effect of Withdrawal:** Upon withdrawal, all processing ceases immediately. All raw document files and overlay images are queued for immediate deletion, and all personal identifiers (name, address, phone/PAN/Aadhaar hashes) are irreversibly redacted from active databases.
