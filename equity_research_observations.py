"""Fixed, verified 89-decision cohort. No approval or production writes."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from zoneinfo import ZoneInfo

from equity_observation_capture import replay

IST = ZoneInfo("Asia/Kolkata")
POLICY = "equity-price-touch-v1-signal-day-inclusive"
PURPOSE = "RESEARCH_ONLY_PRICE_TOUCH"
# IDs and fingerprints derived from the user-exported 2026-09-10 scan, not regenerated scans.
COHORT = {
    "c89039889fab7b7c8d158bd66990483ab5c6fed2225a60346b712d348094c3cb": {
        "event_id": "caa5f632-d55d-43b1-b2af-d30534e64921",
        "payload_sha256": "aa0696c17e041a9156cc0d2b8c703fbc0261de02a98735f693d069094e5a5de8"
    },
    "c263219fa0df33b36620cbd277d93e307e87b952d101b6c99fe965fa70bb1d85": {
        "event_id": "0bda4512-c3f1-46e6-ac8e-bbf7dacd6dd2",
        "payload_sha256": "2760a12cc692959c10c74749f2bae510771a7b296b3430ef36277e7916777baf"
    },
    "7e30de7a539b017da7e45c7a82dcfbe74d083b0f32d8cc3184699706e6160da0": {
        "event_id": "9d049fab-adce-4757-b60a-d0cdccad565f",
        "payload_sha256": "3ea2216cf2e870b524df5a15ab2aa625c447f728d3b7daa392ad2b920ed2b0ca"
    },
    "28552caca316420fdea6cfb6e8db67937670712addae02d331c086f2259aa760": {
        "event_id": "90d9be50-77c8-433f-812d-f66bd36fbfce",
        "payload_sha256": "7fea5914b2b717d54087c15fc52a83d37b83309389dbf65f5c3a1c33738598ea"
    },
    "ec946c62ac366bed852b6f7119b748002b078e47ee24c88970c9d4aea9e5b3c3": {
        "event_id": "80e7cdb5-1594-4303-bc10-8985b90933bc",
        "payload_sha256": "e8935d0d75248ff0f3ae8feb3a2463defe01c2781a57ab42ea1a54567fdc740e"
    },
    "a1b653048aad5ab552573b12fd2be74039a6f2952368accaaa7ccb9efa6d1270": {
        "event_id": "9c1df2aa-566f-4cf8-8572-adfbc2585354",
        "payload_sha256": "218fa2c56e27868c9454b371851639471d2b8540c71ebe78bb41a7c3b22a2f6b"
    },
    "f350f0acca42a6b9f92a5b923ad727a7b639fb7f67d9df2fc62852f4bb272274": {
        "event_id": "6586f8a9-be2c-41ba-bdc1-f90c65f908b9",
        "payload_sha256": "723803f33373a2f9c6902a9486625979c6f2658bbd24c9d7180851b3835f307c"
    },
    "69db30897aefec4158afaa014445748a44dcdcf727c2e4242d33b931dfd5d1de": {
        "event_id": "8208a005-3e85-42c8-8799-86cdb83441ee",
        "payload_sha256": "7a4311ca7b8c94a898e11afa374f573dc1b2bf7896f83849a33e867544b43164"
    },
    "5b3001cbc632d94f205a15eb3389273e3c89e39bfbe14d8683a4a28f1b728d6b": {
        "event_id": "9ee15048-69d9-457d-9064-7629497454e1",
        "payload_sha256": "62af2ca8fb7d6d085e4536b266119bb21ee1148a01a0f4a97f49d23591c4df0d"
    },
    "f77b19c7bf12c035a2ee34eb2eb7e253e8efedf18dce4af2678242e3084eef6d": {
        "event_id": "4f4365f6-cd93-442c-b7fd-afb03d68a353",
        "payload_sha256": "215ba675845c5b607ce9a03b6a97ca6bfd76707c4afca848e53b6ee8da49b231"
    },
    "f1fd0f4c1464e46d84285055adb9ae6b338972ad49631dce83a1be18f26b8679": {
        "event_id": "77d26eae-b0fb-4874-9325-a27f16054fb6",
        "payload_sha256": "ad1d9d097f7e8df446ee5b15cb8e8a92a7a39bddcbd7a81569eb14b3338be56a"
    },
    "e8af1d67f00bc8961a94abe290a6994548883ea4fe8437c4a291789c28e5486f": {
        "event_id": "529174ca-d368-42ab-9ec1-a28ee8c3fb0a",
        "payload_sha256": "37d84dde3d84832d7751b6e0beb435384d45efc706d17f6d2c038c5a980fc0d2"
    },
    "ca66cc70feede1899dc92eb9912a0969d70e7c254d60e70707af3ab7398732cb": {
        "event_id": "c84ab1ff-5528-4c9c-811a-3d35c819d52b",
        "payload_sha256": "3c3762a48a2c9633efe027d8a4fc6cc1ec17258ed404968338063542bab51190"
    },
    "0e60bc69b976fef889034462e9d0b0aba7acd8db02e71a869ed2e4ca53aa65a9": {
        "event_id": "1181d18d-4279-471a-b5a3-03e988e5cb34",
        "payload_sha256": "5465da918057e61e06a605ca3f232b6c15739cee154be3184fc211f5c05ddf20"
    },
    "37e420410adeaeaf04f44ceeacfdfee719c6d1120bba83090104b847aa62d5d4": {
        "event_id": "27bc2443-a6e6-41b9-98f0-fb768b4700f1",
        "payload_sha256": "ec4a7cda1bb52bdfd6ed984bff22fa899f8e47126be205c5c9bdecb7d6508ea8"
    },
    "a3835a6b2856d6a744d9a71684025dfa365db5f38bb3b9ad6a0af30a6cb96092": {
        "event_id": "e4bbf7ba-6581-4751-9909-8ec2581ca8ef",
        "payload_sha256": "c6746e5f325529d38f80630ad2debaa414e23b380142e7934f539b30ad51c6dd"
    },
    "aae585d2083ec85c122febfe040692c0b796ffb8697f4ab007138bf5391decbf": {
        "event_id": "1c27efa7-8dd6-42b5-bf11-45acc70cc8ef",
        "payload_sha256": "cf96601451db04242e7121b7107e666763f8cc5245e5d98e5b5e1e095fc1c9bb"
    },
    "972c76849643f46a5501a5823d040573f25e2822bf58ec412cbd955acb21ef53": {
        "event_id": "bf39d4a8-192f-4bb9-a1b5-b2383a0e9ea5",
        "payload_sha256": "e9b154ba6233224854bff67ccc619e8031ceecce8f7273696d5c33333a822890"
    },
    "c81336e626268950eebcb82e3091699ff90f9ba82ea6a3bf856e303adeb12212": {
        "event_id": "5910e4ff-4a12-4731-b5e2-7a5dfc6b5e5d",
        "payload_sha256": "5b3ba878db4be9e96466039c9fa71795470661ccf4382c4da0855fdf834d2e14"
    },
    "03f5d1a4c2790e3002775110cc1223b43e2ff4ce3d62785af40bc6a3261a4f81": {
        "event_id": "e89319c3-9f65-4d88-b5f3-f532b4e833c4",
        "payload_sha256": "439d86889349cc189a690d08bd86a1d292d418ff6d7e5f7fc14a11dcd28ee8c7"
    },
    "77e9ba44741f343f5d4c70142f461f337daed98e8491e6070b25aaf661c47ff8": {
        "event_id": "3a730f28-f913-4c0e-9735-fe4df9e2cd29",
        "payload_sha256": "80f2ddc06c60e4bcf1e789e12fdce843b937a0496c08df9f8807fd82405503ff"
    },
    "285f574d2ad3d4dbda06bcf509382a2c96e38e4c8d4b3117807c969c16b08f31": {
        "event_id": "ec9f14c1-9573-4aaf-94ed-7630b24fe49f",
        "payload_sha256": "bb87f521f5d20f8601afaaa1f8356e478b419f40660ed128890cdefb20f07f5f"
    },
    "bf051c63ec7ca16aa97f713535730a8247321d887d33b122f66e35618876ab93": {
        "event_id": "d829bbda-0954-42f4-995f-9c8f5f634b1c",
        "payload_sha256": "701d343fb89eb7397373188f74d9fcdca670c52f5c89b4f00e88938191631554"
    },
    "2024bba4b9d354a23dd1da5e1cfefe9a8476f708cb4b0d4d44a086e348df15e5": {
        "event_id": "78c0e38d-c1bc-4092-84a7-15588318d118",
        "payload_sha256": "65cb1dd6289e1d49bfaa2a2d7c8bd9496b19685b6ea4d83ac416e854332d4fe8"
    },
    "0d05bca4357a659c5f37ae5c74e3603747c908dc0a7ed914e2a8cd199aa4c5f8": {
        "event_id": "8aa9c86e-32e3-4298-8aa5-15bede8f9a59",
        "payload_sha256": "a2fbf0aab8a28feb74f088d40abe4c0371e48ce9713627f4ccb69be486fcacbd"
    },
    "6cd785b5b5af2c1a4de3e69abc25d14e3ebf472e81bda702e2defef632863b16": {
        "event_id": "9b7c4499-3f08-4a45-b4bf-9f5094ad2b76",
        "payload_sha256": "d67b91092309263f4e025886af76b3940218994741a955ee6e83fa0e9ac98a69"
    },
    "f6b28627b97d3adf6a1298003f2aa7d312d638dc5642d075d6810a84e7bec6b2": {
        "event_id": "4c6c6441-5818-47bd-b5e1-fd7b1650d82d",
        "payload_sha256": "dac8a0c907fcb388d85cee08364756f02b19fef81a2403cd269f27a5fbcc515b"
    },
    "17f59763a9cb35f95959d46301dc0929543d2dbd78fd61c9b85e05e8a3ba6cda": {
        "event_id": "f29abfff-b361-453f-be5a-b4745e5afff5",
        "payload_sha256": "286ecc8b6b43b7cebc813281d969748dd3ac172fcfe3383bea6abb9e006fa24e"
    },
    "54f56ed7d2655daac6e2349654b2f9c07c0dfe02c7be058cd6e9358afaff2e2f": {
        "event_id": "f91fe96e-fb1b-440e-81ea-f1722a0835fb",
        "payload_sha256": "6c2958a035ecc0e705a94dd4883464f433c11ac4c4e5fa682f4acad4f0aa605c"
    },
    "8ade2fda7a1875f774d5ca83800184ffdabe35b5d89218e43fa64965e0ff8d4a": {
        "event_id": "9608a675-97ef-4839-a20d-75fa09168edf",
        "payload_sha256": "e42f2f751eb8f691a746747bf8288b85927192960d4408b5b92d650b76a734d1"
    },
    "126a0408b087eb53ffa5d3f308e7f7f4f0a575b575f4b45688acbeb4d2888ed9": {
        "event_id": "e23d30ab-90c6-49ea-824b-e672cb8bfc3d",
        "payload_sha256": "d7b388d0706355bb873ae81123ae3db88a5a6715e64c902a396a7eee7b8b1f89"
    },
    "b239e610799c9c048b13f0accaa2c889bf9a8d87e11295c7c8e9266c6c5531f1": {
        "event_id": "f8260c27-a3c7-40ac-886f-79084501c34d",
        "payload_sha256": "c9f8fbbf77ff9c41b7cb248773868da4fd2b891a625a61d4c04ef2150fac435d"
    },
    "9cd249b199ed24565bed7f081c277842f300d143d3c9b995b04d352d357772bd": {
        "event_id": "55a1fdf4-6906-4f92-ac72-6ac1f4668962",
        "payload_sha256": "2cd8fd63c86c7f7068ffa6e1d75e279b27b2932172080cb0d244ac5172c9c4a1"
    },
    "ec4c7cd09e678ddf6c2fcda5eb1796d04df6fa30e9834febf0f27612a770597c": {
        "event_id": "45884785-881b-4669-bffe-49abaf1c5b40",
        "payload_sha256": "2a9fa6a558e611477ad37d0b4349d4dce9233ff61b1e2fb056a7ca0fc78da785"
    },
    "980c75798b355d49008659c92eb77f9a923b0e06da8833cbd7b4da877420c48c": {
        "event_id": "84c02cca-bbe9-4e3c-b34f-e6fece700d73",
        "payload_sha256": "a9a949fbf7e4d25f07a5e2c58c18dfa4e0a495a338f5bc40a607e8b94ac4ece0"
    },
    "4f8f81c138b0ab22020f730725e794704f527215672b0c8027abe71366a73100": {
        "event_id": "3b04f83b-9ee4-435f-b6a0-1017e1a5b04a",
        "payload_sha256": "11aea5049dc2bfa8e397ceaf3bf0dbcd407389aa5ab09cfd9a468a439dea67fa"
    },
    "ebcf86dbc3439be65253c99ad3135b048dca5253336fa172236f738a07d31f8d": {
        "event_id": "f69de1cf-019c-4016-ad18-2a0c5cd22b79",
        "payload_sha256": "f9586752e7850c039c0fc1d3f9947b5dcd434b2869161ba4b68858001ae4ff77"
    },
    "ae36d74b878f19956a9569dc5b08617644212913c2a4256afe3e9227af66d64f": {
        "event_id": "1d6b133c-bc1f-4502-91ef-bb5bae853534",
        "payload_sha256": "1276da2f22388089776cb5c5daa4c2447e8857542e82fe5cda3c3b0aff357ad9"
    },
    "b585f3aa200cffcf2f14b68534faf33439e17f079d3e470c17532f8d1d2ad49a": {
        "event_id": "c9a0e42f-9239-46ed-903c-ac1215f2993e",
        "payload_sha256": "3d566329f776076a0607e69d928d65011b58c801411c69b7f6d55a498d5fb3d9"
    },
    "b27be068a3f3b6abdf4238806dbfa49030b73864e2c692053bac1c212f15e8d5": {
        "event_id": "0c92acec-ec62-47ba-848a-4a22ceac533d",
        "payload_sha256": "24f814d9e0c19cc57f3ee29e5244fd618e0369c53af4e4cd2a7befa30cb42f6f"
    },
    "d98c2ac232bc778b7e2dd794c278b596f447ac69d34ab8f46b5ce8879dbecda2": {
        "event_id": "10d6e6ad-00a2-48e5-8d48-76ca4fbd5027",
        "payload_sha256": "aa962d4947177f93667e63f62014dc325f347c702bf75a3a12b0cf5b3ffc20fd"
    },
    "fd0b33b4d87ce91c253735dd5eca435a68ab0be61542e82cec37663c016be72d": {
        "event_id": "53203b4e-ae1b-42c7-851e-66d2a6b2a29d",
        "payload_sha256": "a297ab6a6c8fb7615804a1e3fbc73732c4b4deedb940284badb36e85f2451600"
    },
    "fd9a4061604c1ef1051e9c2f835146eb9dcef0df1f325ed4cf4420753e2aa0dd": {
        "event_id": "7f30f737-4208-43de-b107-a2fa3b769218",
        "payload_sha256": "68b77b386cd393368d814d546ebd435cea43933da418ff56f5bf59591566768e"
    },
    "a5de78002c2c299af933537010998932abd03d9188793570c6ee88070620d1b1": {
        "event_id": "210b8cba-b0b5-49ae-a663-acfd8d2716c2",
        "payload_sha256": "9bff4b7ba3406a1489a3efa90954957618771a845677416fa208f1717aedc221"
    },
    "16e734a2338737c6e12fb711f6ce1b01a2af892277292dd43e24bf7c4635174e": {
        "event_id": "e5228eac-7fa3-4723-98e9-a994f9688afa",
        "payload_sha256": "b98582c68c44315219f49407802b0df584fe3f821cbf74d7bcf57cb2f9975b69"
    },
    "737b9a46215b1d9ece4112fd23093589aa8b27f67218493f8cfd91bc67ab6a75": {
        "event_id": "758997ee-9506-43b2-a51d-ab0f6c8ce735",
        "payload_sha256": "7a1d249c609d6017c6b29ce0dd86b66958b5c32d9a8b30ca0d6233678f6c80fb"
    },
    "2512f518d605114a416dbf15a59eb8312d413f66a72ce41a0fdceccd37ac841f": {
        "event_id": "a125b100-f7d6-428c-a6d2-6fc42977a05e",
        "payload_sha256": "3852b05b8f9a50c3e700d3c25237f3ebae9b8417a881f14c9b2345b89bef3a36"
    },
    "fae5e9733adb15e0ea412953454cb829a627b85c5f0ade317e5935270cf2b2e5": {
        "event_id": "752ccf86-4099-4118-849e-4ba74d285e02",
        "payload_sha256": "773efb58ff02465b007695ee461fdcdc4d05bdfd4cc80bf1ec9b94086bd07ca5"
    },
    "7f38dff9693d2094d57486f44831c7b9beae01590a61fad5786a0a1e20b8d4af": {
        "event_id": "77f15f72-60af-4672-9be6-7810ecf8a58b",
        "payload_sha256": "8a5584f0e99fdd207b1199fa1276eb76287d745e55133b4291f5d1e84b0d2e93"
    },
    "22f179a8c7e209320e1acb1a798cf381061f0dacb6eca734f1273ec43d650de3": {
        "event_id": "a689118d-f1cf-4621-888d-91f2adb487e7",
        "payload_sha256": "af89ffd2442c03a6e59f0c745a1a66846a1c4a86c7b22d7c4a951da0e8ef17da"
    },
    "4161b35bc218ae4d17608a65a7dde6efc2e963ed798d33cb8a44660773c384d2": {
        "event_id": "b5077cce-87f5-47a2-a6e5-eb5dd41adc8d",
        "payload_sha256": "89edb15d1abac5715d931409eb4cf4453ea0d8bf62c54e28ad95af3c89ef553e"
    },
    "f9c8b1f9a62be375b8de11d2d299445e44b5478e4b48b69543a2d92c96088b3b": {
        "event_id": "85a4e8eb-070c-4e1d-bfdc-8a7dbde0c2f3",
        "payload_sha256": "090884b4e4f90c2e2ae8f89755a7d0be70ef8733d36de407ab06b8b317b6bc4b"
    },
    "2b7baf5f94d298e1c8ccca69620de294d346457f0e58caeb0310067404075bc5": {
        "event_id": "759b004d-59a2-4bc4-9502-b329306a5749",
        "payload_sha256": "1a56c41e12f64e6293e8059a39f905db699a9499b6bf6eaec9a1949010f92937"
    },
    "f305f63331ee7ec7acaa27104e87368be313eb8ddcba08a20d01f786c151839b": {
        "event_id": "017117f0-7589-42e0-a999-a2c75d3525d2",
        "payload_sha256": "d7ded7d521e976303a6c222279e30cfe4d652fef8b83934d77333846517301cd"
    },
    "4c7444204ce545f950fc58b16c8aaeebf3046ed940ddf055aa5f9fdf18465a36": {
        "event_id": "eac9c03f-ed22-43e9-adee-681c2235c56d",
        "payload_sha256": "3906a39222ddc7433569342e35ba9c76de9a8cff5814e89e31fe1ada461bc028"
    },
    "31b8daf9cf9edad3fab82a3d66277bdfca2ba709bc4e4ac8a85d56f10d32ee55": {
        "event_id": "9d49cce9-4747-4822-8390-5886e4be05e3",
        "payload_sha256": "33e55e062e348a5bd68083e5a2e1c5bbb263e369742406f673e70c03824cbb6e"
    },
    "a142d14648706bcb6c9fb1506a390169040e9eb6c4b840db88b10351ed915ea6": {
        "event_id": "10661b29-59cc-4454-b5ff-2bcc6e287e1c",
        "payload_sha256": "36b885374d06e0571d33aad6240bcc7180bef29e41fa777d23cae0ab92e06531"
    },
    "244871be18646f493bc3b467bf2d60b05497922780709233c1b4e518191ac9eb": {
        "event_id": "ec9c45f8-496a-45b4-8c84-60ce87df1447",
        "payload_sha256": "fb208e456ecf4f1b74151831453042479a7b7d906e5b7a1cc849a20626ca24a4"
    },
    "bc8f52e49dea163a742978ea2361707002dacb5897a9ac49cbadfc53eeb0c4fe": {
        "event_id": "dc6ee654-0a01-471d-9234-4c230648c0b6",
        "payload_sha256": "0ec2137227eb2071f3ed86842d34687905a89ecece53d11160d2c271cd3f580e"
    },
    "6660c93d6575677d3e7211e8614755d477ae08684a6ebae7d8f3c638d05a3b89": {
        "event_id": "324fb7ab-0f59-46ea-a125-b7a8d4405acd",
        "payload_sha256": "3cf54fdea3eb64a911a49844ace13c6be59dd0e184b9463ccc315c9bb76e7e09"
    },
    "2a54e12102f39d11d7bfc4a415019352f1c15d1659b24ecd859eb5f7476f47ec": {
        "event_id": "93566fbb-9095-4ca0-a6d3-16011c5bbe38",
        "payload_sha256": "33d6265098ff3f59d215e3596457f1cb600694463dd86ab86e9f15e735352b91"
    },
    "8fd42d4f91d94aa694c7992dda7e7712574ea4d17b5f9a5b0f87ea31e5ffca34": {
        "event_id": "24c0f1f1-1563-4842-a0fa-0520409d136e",
        "payload_sha256": "c6fd54a7131712092cbed56c503106ca5e482495f4857209e5fbb4a395ce93bc"
    },
    "7064bcbdb34f50a1322d854cd52f04f4d57b24e9b7643efb2e1db50aa6e3d786": {
        "event_id": "1517ab15-ffd6-41a3-b401-8fbba18524d6",
        "payload_sha256": "3a3dceeade78b0f6c4f51509a2851bac3f6c5c92c8a53fc1c70f4ea2647d2f36"
    },
    "2fc5d3942bf83996526438e5b174794bfae83328c2f9e00795899e0a980f6a79": {
        "event_id": "9a9dd303-b89c-4e5e-bf06-17f8ab6be037",
        "payload_sha256": "69d760b1ea674a0579d63c5d05cb8526c9c765baaf7ae871f31097119dac37b8"
    },
    "0c058a6f72d226dc3566a13bdf49f6c9fde436579ec9fe5feba0e7d4e007d54b": {
        "event_id": "ee5d6e92-fed4-47da-a7a7-384b3a823604",
        "payload_sha256": "f938254946cd630cc7b57b3a09a24031e3472074741b8fe4e0156dab53c2c76d"
    },
    "c7241032ca40e2c909a63e740f9111becaec65fdf40f5863c30fb974726e258f": {
        "event_id": "8e6d56a8-b8d3-4eaa-aa84-04efe48be921",
        "payload_sha256": "28306844f4aa39cc87eef705c337d826a0858d1e1523cf71f99d4e51f1724b87"
    },
    "2f61d45e51c6d2833d7d7afbcbafddc58b3ff7497ed972c633c5d5c7208e9728": {
        "event_id": "2eb28f7f-126b-4ee9-94d2-7f2d41be7a70",
        "payload_sha256": "3b8ff7debffe9b27b97e698141fa9d9c0467dc159d17ee5bd37134b60784aa1a"
    },
    "68ff5a84eae645ee08b69dd3b8179610a316726ab4e3b7a71dd74b4f9f260656": {
        "event_id": "716f993f-6dfa-4f33-a084-f81b9086f688",
        "payload_sha256": "fdcb519dc79bad5280533ee1ab49f350516546196e03fccd48f99d16bf67d5e3"
    },
    "d7cf54d2531bab21cd384b57569f204b0e2c3e21229ea74b508ec015ea2013d7": {
        "event_id": "4bdc59ee-821c-45e2-84d5-82a46c559b7f",
        "payload_sha256": "1d3d2328b241c61f6fdd8b15f9864cb112547b74016b6946eb9bebe9fec233df"
    },
    "add896b84f11feb1b88fca6bd4d4b1ebfb86df743a4b7c9ba277ae9c4786aac5": {
        "event_id": "d308f7ce-4f10-40ac-b354-f51ba29dee7e",
        "payload_sha256": "95d49a58df36f66939ac12692b8b2ffd51f19b89de13dd7dedd1eb01dfdf6f15"
    },
    "3da8f4102c008ab82c42b3b388dee103c1cd9b36fda46f1c5b5956d309a659e2": {
        "event_id": "ef0a0b6e-05ae-4025-b9a6-054a815b416a",
        "payload_sha256": "65c5c8d7e34cc6a0f4b8f88c8c5a908829bd11007bedffdb13b0280c9feb2232"
    },
    "915b50ef7ceae3f6a9bbb6378fb964a9adc423438184d8e93811e2ac4115c54b": {
        "event_id": "73cf92f5-b264-4284-9947-98605c0349e3",
        "payload_sha256": "9d187e08db4af60100611af4af991d066f7497c5aaa4c1e29df32d909b4b73b8"
    },
    "1dd735cd642375a465d6900aa9c44d209189894146fd7441635be05c02de91b7": {
        "event_id": "930cdcfc-31a9-44b5-92ff-bea225e00463",
        "payload_sha256": "09fcd3f63b4f93293aa2c1d7354fdbe3d333770f54cce308d03b47b33a08bd24"
    },
    "7fd4e4ec57144ad0f831c89e9b2926cab829a135e16c654caf2faae0e86f5863": {
        "event_id": "1197c950-16e5-43d0-a1c8-a08dee95ddad",
        "payload_sha256": "9ace73dba2b173a8e7159f5f43aa84b2f9285ba9076b5622c6c546f86f7c7449"
    },
    "b053304711c44baa05d4c51c1f184c14b40f8b1f331c8674dda71153e7fb3925": {
        "event_id": "989204c1-1024-4318-b416-b565c7729398",
        "payload_sha256": "fa77b98e62bc0707f0a2c8129791ce8e6a38fc5bca426fa4f8def778723a8f75"
    },
    "b81fcda58f6fc0231dbb9b27ac864feb7f8be057589f24341695720a284ae34f": {
        "event_id": "f0bb5c67-e249-4ecb-b4d7-f2016b86fa1d",
        "payload_sha256": "b83ef6cc59b1b3ee71ae5594fcb53de25b3a93ac8511708ffb2b304dd0842571"
    },
    "5c368c4436a78de49158f8e99552bf6e60cbc77abcfc80dd0ab72fa09f941812": {
        "event_id": "dcbde599-060a-4176-8563-fef51a737733",
        "payload_sha256": "b0d85972aaff70902bdc05ac17f5e85360e8f34ba6b2750da3bef10a6d25b421"
    },
    "bbd64a2cac710720e5353c1cbdafe20a5ebfab35c5e9e10c702b4062eafc0753": {
        "event_id": "58865d76-abd8-4967-a5ce-f27a427099fe",
        "payload_sha256": "935c447b2c3d19cd627f64a526005e13c9f7f2e5a3d402474a872fc21a564628"
    },
    "b6aba14f719caa263cd6cfa83556e8e8a8bdf174be6f70fbcdb2d9705c0d3880": {
        "event_id": "b5aa3a13-b333-47a7-838c-788687e0bb7a",
        "payload_sha256": "5f904a8935b96f22a94965ed03abcd0cf66c1f9c9a4e65010e9da577ce2a045f"
    },
    "ef979a5ba4abb4a2f4bfcb67088cc17ebad9734ea7e656fa0f8c94b97b94a7a6": {
        "event_id": "714ceb17-b138-4851-9777-776c245e31c4",
        "payload_sha256": "57e4c639562197005725564fcbd1a9a19fc2fefac1ac100380eced968aedd75f"
    },
    "ce5b609f6acf2202f5402504bc638d909200c3948983e0b4e005517136eec157": {
        "event_id": "6475a00a-0b61-420d-8447-4170dc99a599",
        "payload_sha256": "95208beabf51ce5a85acba469ab69f1f426ccd160eb06b84fdd14d6634dcaf2a"
    },
    "19b6de1018475e496df104bc4fc84f0c55014b5b0a3721d1c5f7af0b349071bf": {
        "event_id": "918f0004-e644-4388-9d23-2c7b3ccd6c72",
        "payload_sha256": "74db93f79747c646b36aab5f4cb82878d2e6b12de865ddcfe64dd420e193029e"
    },
    "fb7e2f09760bd63b4b015f0c85ba9a900739e37dd5790a114aa13d0ab606cee0": {
        "event_id": "e05985f8-206e-49c0-806e-84bae53a2781",
        "payload_sha256": "27f417f9b20dfd4783508b038d4455e398f3cedea40503455967c450960bee97"
    },
    "a5e70f8ac85aea9bceebdc34172666a48b7138d06268d14be8da717547269e52": {
        "event_id": "b1e85c88-98d9-4673-842a-af01277b773a",
        "payload_sha256": "6310d9c227eaf2f0e36f05dd71464382194451805b76101616e6dd5bf47f0a4b"
    },
    "db11c3bde5e9cd906279f1c8127dab56179277c80c6798e47fc58953579114a7": {
        "event_id": "51fc97b2-4bc6-4ea7-93ad-45d9ecb52f1e",
        "payload_sha256": "1c9d2fa8e9a4e14d64eee2572d391f2fe897479529a78912fdb70da6345b0b55"
    },
    "acb5aca0684394ba0e447b2b3866f7ad716b7e7590b5713df58b657a4baf1506": {
        "event_id": "494421c0-b453-4296-ad84-375f3aae5294",
        "payload_sha256": "f35247afd0926820cc934e263ad40f9816996592b4471550b3ac67ec67cd181d"
    },
    "d3f6e0ba73a2854f54f6816267e47530b7d47193e34d1bd70ba0adbe2d068e79": {
        "event_id": "ef6d5b58-ff51-4e0b-8556-7cbb17b98e7c",
        "payload_sha256": "18e57ceb2cfe6eb31a52356009d86667b859f1ae32bca12f6ab98bc291dcfd4f"
    },
    "53275c46700a3b1ed75ed731d837b53cf661ce844fbc8c7ce9ada9803bf9b3d4": {
        "event_id": "32ad2b0b-ff1c-4e81-a293-e7358d7b38ac",
        "payload_sha256": "9f45441e5d70b638593942664bd5928fc8ea53e4dea14c077012454fd926d343"
    },
    "048c3afb66eb3d1db38b9d25bf76974171538d7674adcc680d6a0a4a40ee3a34": {
        "event_id": "3c0bdfcb-57d8-4ef2-af4f-bb25cc99105d",
        "payload_sha256": "a1c3861e8e0c860b8b2abebd09724f5a574020d8d5948a699c61c7d54ebbc7f5"
    }
}

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def aware(value):
    stamp = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Timezone-aware timestamp required")
    return stamp


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Captured finite number required")
    return value


def enroll(source, *, now):
    """Validate a frozen source; never fill absent inputs or recompute replacements."""
    now = aware(now)
    payload = source["payload"]
    identifier = payload["decision_id"]
    expected = COHORT.get(identifier)
    if expected is None or str(source["event_id"]) != expected["event_id"]:
        raise ValueError("Outside approved 89-decision cohort")
    if digest(payload) != expected["payload_sha256"]:
        raise ValueError("Source payload differs from verified export")
    if not source.get("event_hash"):
        raise ValueError("Original ledger event hash required")
    ids = payload["identifiers"]
    if (ids["asset_class"] != "equity" or ids["strategy_id"] != "equity-scanner-v19.0"
            or ids["target_version"] != "net-excess-execution-v2"
            or ids["horizon_sessions"] != 15 or payload["action"] != "No Trade"):
        raise ValueError("Unexpected source decision contract")
    capture = payload["features"]["raw_values_used"]["equity_capture"]
    data = capture["inputs"]
    if capture["schema"] != "equity-observation-capture-v1":
        raise ValueError("Unknown capture schema")
    number(capture["scanner_composite_score"])
    if data.get("scanner_components") is None or data.get("trade_math") is None:
        raise ValueError("Incomplete observation")
    replayed = replay(capture)
    if (replayed["scanner_composite_score"] != capture["scanner_composite_score"]
            or replayed["trade_math"] != data["trade_math"]):
        raise ValueError("Stored mathematics fails exact replay")
    entry, stop, target = (number(data[k]) for k in ("price", "sl", "tgt"))
    if not 0 < stop < entry < target:
        raise ValueError("Invalid original levels")
    if capture["settings"]["horizon_sessions"] != 15 or capture["settings"]["minimum_net_rr"] != 1.3:
        raise ValueError("Unexpected captured policy")
    if any(payload["levels"][k] != v for k, v in
           (("entry", entry), ("stop", stop), ("target", target))):
        raise ValueError("Capture and decision levels disagree")
    decision_at = aware(payload["decision_at"])
    if now < decision_at:
        raise ValueError("Enrollment precedes decision")
    key = capture["quote"]["raw"].get("instrument_token")
    if not isinstance(key, str) or not key.startswith("NSE_EQ|"):
        raise ValueError("Captured instrument key missing")
    return {
        "decision_id": identifier, "source_event_id": str(source["event_id"]),
        "source_event_hash": source["event_hash"], "source_payload_sha256": digest(payload),
        "policy": POLICY, "purpose": PURPOSE, "approved": False,
        "instrument": ids["instrument"], "instrument_key": key,
        "decision_at": decision_at.isoformat(), "enrolled_at": now.isoformat(),
        "retrospective_enrollment": True,
        "entry_reference": entry, "stop": stop, "target": target, "horizon_sessions": 15,
        "original_action": payload["action"],
        "original_governance": payload["governance"],
        "capture": capture,
    }

