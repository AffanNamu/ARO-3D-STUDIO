-- Migration 0002: TripoSG's licence record was incomplete. Read 2026-11-13 in VAST-AI-Research/TripoSG at commit fc5c409:
--   * the repository LICENSE and the Hugging Face weights card say MIT;
--   * BUT triposg/models/transformers/triposg_transformer.py (the core model) is adapted from Tencent HunyuanDiT and carries the
--     Tencent Hunyuan Community License (not valid in the European Union; Acceptable Use Policy; Outputs may not be used to improve
--     another large language model; the use restrictions must be in your terms of use; >100M monthly users needs Tencent's licence);
--   * triposg/LICENSE is the Tencent Hunyuan FlashVDM Community License for the FlashVDM-derived decoder (not valid in the EU, the
--     United Kingdom or South Korea; Acceptable Use Policy; Outputs may not be used to improve another AI model; >1M monthly users needs
--     Tencent's licence).
-- A verification recorded before this correction was made on incomplete information, so it is withdrawn: a person must read the terms
-- above and verify again (python -m aro_cloud.admin verify-model). The status stays 'claimed', never 'verified', by this migration.
update model_registry
   set code_licence_spdx = 'MIT AND LicenseRef-Tencent-Hunyuan-Community AND LicenseRef-Tencent-Hunyuan-FlashVDM-Community',
       weights_licence = 'Weights MIT (card). Model code includes Tencent Hunyuan (DiT) and Tencent FlashVDM community licences: '
                         'NOT valid in the EU, UK or South Korea; Acceptable Use Policy; Outputs may not improve other AI models; '
                         'use restrictions must appear in your terms of use; over 1M monthly active users needs a Tencent licence.',
       weights_licence_url = 'https://github.com/VAST-AI-Research/TripoSG/blob/main/triposg/LICENSE',
       licence_status = 'claimed',
       verified_by = null,
       verified_at = null,
       enabled = false
 where model_id = 'triposg';

insert into audit_log (actor_id, action, target, detail)
values (null, 'licence_correction', 'triposg', '{"migration": "0002", "reason": "Tencent community licences found in the model code"}'::jsonb);
