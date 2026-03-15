# -*- coding: utf-8 -*-
"""
Created on Sat Mar 14 21:45:39 2026

@author: cocol
"""

import qrcode
import os
from paynowqr import PayNowQR

# 1. SET YOUR DETAILS
recipient_info = "+6589567959" 
amount = ""
reference = ""

# 2. SET YOUR SAVING PATHWAY (URL)
# Windows example: r"C:\Users\YourName\Desktop\paynow_qr.png"
# Mac/Linux example: "/Users/YourName/Downloads/paynow_qr.png"
save_path = r"C:\Users\cocol\OneDrive\Desktop\fortune-bot\paynow_qr.png" 

# 3. CREATE THE PAYNOW DATA
paynow = PayNowQR(recipient_info, amount, reference)
qr_string = paynow.create_payload()

# 4. GENERATE AND SAVE
# Create the directory if it doesn't exist
os.makedirs(os.path.dirname(save_path), exist_ok=True)

qr_img = qrcode.make(qr_string)
qr_img.save(save_path)

print(f"Success! Your QR code is saved at: {save_path}")

# Optional: Automatically open the image to view it
# qr_img.show()