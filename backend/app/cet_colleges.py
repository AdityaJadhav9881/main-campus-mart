"""Maharashtra CET Cell / DTE college directory.

Backs the College Network feature: the Sign Up / Profile college picker, the
Discover "My College" filter, and same-college notifications.

Each entry carries the institute's DTE / CET Cell 4-5 digit institute code
(as printed on CAP option forms), the official name, a short alias used by
students in practice ("COEP", "VJTI", "PICT", ...), its city, and extra
search aliases. `search_colleges()` powers `GET /colleges?q=&city=` with a
relevance ranking (code match > alias > prefix > substring). Students whose
institute is not listed can still register with a custom college name typed
into the picker - the DB stores plain strings, so custom entries "just work".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

__all__ = [
    "CetCollege",
    "CET_COLLEGES",
    "CET_CITIES",
    "search_colleges",
    "get_college_by_code",
    "get_college_by_name",
    "college_to_dict",
]


@dataclass(frozen=True)
class CetCollege:
    """One Maharashtra CET Cell institute."""

    code: str                  # DTE / CET Cell institute code, e.g. "6006"
    name: str                  # official institute name
    short_name: str            # student shorthand, e.g. "COEP"
    city: str
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def search_blob(self) -> str:
        parts = [self.name, self.short_name, self.city, self.code, *self.aliases]
        return " | ".join(parts).lower()


# ---------------------------------------------------------------------------
# The directory. Grouped by region for maintainability; the runtime order is
# irrelevant (search re-ranks per query).
# ---------------------------------------------------------------------------

_ENTRIES: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = (
    # --- Pune region -------------------------------------------------------
    ("6006", "COEP Technological University, Pune", "COEP", "Pune", ("College of Engineering Pune", "COEP Tech", "COEPTU")),
    ("6005", "Government College of Engineering, Karad", "GCOEK", "Karad", ("GCE Karad", "Government Engineering Karad")),
    ("6007", "Walchand College of Engineering, Sangli", "WCE", "Sangli", ("Walchand Sangli", "WCE Sangli")),
    ("6271", "Pune Institute of Computer Technology, Dhankawadi, Pune", "PICT", "Pune", ("Pune Institute of Computer Technology",)),
    ("6273", "Bansilal Ramnath Agarwal Charitable Trust's Vishwakarma Institute of Technology, Bibwewadi, Pune", "VIT", "Pune", ("Vishwakarma Institute of Technology", "VIT Pune", "VIT Bibwewadi")),
    ("6138", "Vishwakarma Institute of Information Technology, Kondhwa, Pune", "VIIT", "Pune", ("Vishwakarma Institute of Information Technology", "VIIT Pune")),
    ("6146", "MIT Academy of Engineering, Alandi, Pune", "MITAOE", "Pune", ("MIT Alandi", "MAE Alandi")),
    ("6114", "MIT World Peace University, Kothrud, Pune", "MIT-WPU", "Pune", ("MIT WPU", "MIT Pune", "MIT College of Engineering", "MIT Kothrud")),
    ("6284", "MIT Art, Design and Technology University, Loni Kalbhor, Pune", "MIT ADT", "Pune", ("MITADT", "MIT ADT University")),
    ("6175", "Pimpri Chinchwad Education Trust's Pimpri Chinchwad College of Engineering, Pune", "PCCOE", "Pune", ("PCCOE Nigdi", "Pimpri Chinchwad College of Engineering")),
    ("6278", "Pimpri Chinchwad College of Engineering and Research, Ravet, Pune", "PCCOER", "Pune", ("PCCOER Ravet",)),
    ("6141", "Jaywant Shikshan Prasarak Mandal's Rajarshi Shahu College of Engineering, Tathawade, Pune", "RSCOE", "Pune", ("Rajarshi Shahu College of Engineering", "RSCOE Tathawade", "JSPM RSCOE")),
    ("6177", "Sinhgad Technical Education Society's Sinhgad College of Engineering, Vadgaon, Pune", "SCOE", "Pune", ("Sinhgad College of Engineering", "SCOE Vadgaon")),
    ("6204", "Sinhgad Academy of Engineering, Kondhwa, Pune", "SAE", "Pune", ("Sinhgad Academy", "SAE Kondhwa")),
    ("6203", "MKSSS's Cummins College of Engineering for Women, Karvenagar, Pune", "CCOEW", "Pune", ("Cummins College", "Cummins Pune", "CCEW")),
    ("6156", "Dr. D. Y. Patil Institute of Technology, Pimpri, Pune", "DYPIT", "Pune", ("DY Patil Pimpri", "DYPIT Pimpri")),
    ("6182", "Dr. D. Y. Patil College of Engineering, Akurdi, Pune", "DYPCOE", "Pune", ("DY Patil Akurdi", "DYPCOE Akurdi")),
    ("6294", "Marathwada Mitra Mandal's College of Engineering, Karvenagar, Pune", "MMCOE", "Pune", ("MMCOE Karvenagar", "Marathwada Mitra Mandal")),
    ("6249", "P.E.S. Modern College of Engineering, Shivajinagar, Pune", "MCOE", "Pune", ("Modern College of Engineering", "PES MCOE")),
    ("6281", "AISSMS College of Engineering, Kennedy Road, Pune", "AISSMS COE", "Pune", ("AISSMS College of Engineering", "AISSMSCOE")),
    ("6221", "AISSMS Institute of Information Technology, Kennedy Road, Pune", "AISSMS IOIT", "Pune", ("AISSMS IOIT", "IOIT Pune")),
    ("6116", "Zeal Education Society's Zeal College of Engineering and Research, Narhe, Pune", "ZCOER", "Pune", ("Zeal College", "Zeal Narhe")),
    ("6275", "Shivnagar Vidya Prasarak Mandal's College of Engineering, Malegaon (Baramati)", "SVPM COE", "Baramati", ("SVPM Malegaon", "SVPM Baramati")),
    ("6274", "Pune Vidyarthi Griha's College of Engineering and Technology, Pune", "PVG COET", "Pune", ("PVG COET", "PVG College Pune")),
    ("6270", "Rayat Shikshan Sanstha's Karmaveer Bhaurao Patil College of Engineering, Satara", "KBP COE", "Satara", ("KBPCOE Satara", "Karmaveer Bhaurao Patil College of Engineering")),
    ("6009", "B.K.P.S. College of Architecture, Pune", "BKPS", "Pune", ("BKPS College of Architecture",)),
    ("6209", "Alard Charitable Trust's Alard College of Engineering and Management, Marunji, Pune", "ALARD", "Pune", ("Alard College Marunji", "ACEM Pune")),
    ("6187", "Genba Sopanrao Moze College of Engineering, Balewadi, Pune", "GSMCOE", "Pune", ("GS Moze", "Moze College Balewadi")),
    ("6237", "Padmashree Dr. D. Y. Patil Institute of Engineering, Management and Research, Akurdi, Pune", "DYPIMR", "Pune", ("DY Patil IMER", "DYPIEMR Akurdi")),
    ("6283", "Nutan Maharashtra Institute of Engineering and Technology, Talegaon Dabhade, Pune", "NMIET", "Pune", ("NMIT Talegaon", "Nutan College Talegaon")),
    ("6322", "Sai Charitable Trust's Siddhant College of Engineering, Sudumbare, Pune", "SCE", "Pune", ("Siddhant College of Engineering",)),
    ("6207", "Smt. Kashibai Navale College of Engineering, Vadgaon, Pune", "SKNCOE", "Pune", ("Kashibai Navale", "SKNCOE", "STES SKNCOE")),
    ("6280", "NBN Sinhgad School of Engineering, Ambegaon, Pune", "NBNSSOE", "Pune", ("NBN Sinhgad", "NBNSSOE Ambegaon")),
    ("6287", "Nutant Maharashtra Vidya Prasarak Mandal's Shree Ramchandra College of Engineering, Lonikand, Pune", "SRCOE", "Pune", ("Ramchandra College Lonikand",)),
    ("6293", "Sinhgad Institute of Technology and Science, Narhe, Pune", "SITS", "Pune", ("SITS Narhe",)),
    ("6644", "Indira College of Engineering and Management, Parandwadi, Pune", "ICEM", "Pune", ("Indira College Parandwadi", "ICEM Pune")),
    ("6628", "Dhole Patil College of Engineering, Wagholi, Pune", "DPCOE", "Pune", ("Dhole Patil", "DPCOE Wagholi")),
    ("6155", "G. H. Raisoni College of Engineering and Management, Wagholi, Pune", "GHRCEM", "Pune", ("GH Raisoni Wagholi", "GHRCEM Pune")),
    ("6304", "Trinity Academy of Engineering, Kondhwa-Saswad Road, Pune", "TAE", "Pune", ("Trinity College Pune",)),
    ("6112", "Vishwakarma Institute of Management, Kondhwa, Pune", "VIM", "Pune", ("Vishwakarma Institute of Management",)),
    ("6113", "Vishwakarma College of Arts, Commerce and Science, Pune", "VCACS", "Pune", ("Vishwakarma Arts Commerce Science",)),
    ("6285", "All India Shri Shivaji Memorial Society's Polytechnic, Pune", "AISSMS Poly", "Pune", ("AISSMS Polytechnic",)),
    ("6101", "I2IT - International Institute of Information Technology, Hinjawadi, Pune", "I2IT", "Pune", ("International Institute of Information Technology", "I2IT Hinjawadi")),
    ("6799", "Pune Institute of Business Management, Balewadi, Pune", "PIBM", "Pune", ("PIBM Pune",)),
    ("6333", "Suryadatta Institute of Management and Mass Communication, Pune", "SIMMC", "Pune", ("Suryadatta",)),
    
    # --- Mumbai region -----------------------------------------------------
    ("3012", "Veermata Jijabai Technological Institute (VJTI), Matunga, Mumbai", "VJTI", "Mumbai", ("Veermata Jijabai Technological Institute", "VJTI Matunga")),
    ("3036", "Institute of Chemical Technology, Matunga, Mumbai", "ICT", "Mumbai", ("ICT Mumbai", "UDCT", "Institute of Chemical Technology")),
    ("3004", "Sardar Patel College of Engineering, Andheri, Mumbai", "SPCE", "Mumbai", ("Sardar Patel College of Engineering", "SPCE Andheri")),
    ("3035", "K. J. Somaiya College of Engineering, Vidyavihar, Mumbai", "KJSCE", "Mumbai", ("KJ Somaiya College of Engineering", "Somaiya Vidyavihar")),
    ("3209", "K. J. Somaiya Institute of Technology, Sion, Mumbai", "KJSIT", "Mumbai", ("KJ Somaiya Institute of Technology", "KJSIT Sion")),
    ("3082", "Sardar Patel Institute of Technology, Andheri, Mumbai", "SPIT", "Mumbai", ("Sardar Patel Institute of Technology", "SPIT Mumbai")),
    ("3182", "Thadomal Shahani Engineering College, Bandra, Mumbai", "TSEC", "Mumbai", ("Thadomal Shahani", "TSEC Bandra")),
    ("3217", "Dwarkadas J. Sanghvi College of Engineering, Vile Parle, Mumbai", "DJSCE", "Mumbai", ("DJ Sanghvi", "Dwarkadas Sanghvi")),
    ("3185", "Fr. Conceicao Rodrigues Institute of Technology, Vashi, Navi Mumbai", "FCRIT", "Navi Mumbai", ("FCRIT Vashi", "Concicao Rodrigues")),
    ("3221", "Vidyalankar Institute of Technology, Wadala, Mumbai", "VIT Mumbai", "Mumbai", ("Vidyalankar Institute of Technology", "VIT Wadala")),
    ("3008", "Vivekanand Education Society's Institute of Technology, Chembur, Mumbai", "VESIT", "Mumbai", ("VES Institute of Technology", "VESIT Chembur")),
    ("3181", "St. Francis Institute of Technology, Borivali, Mumbai", "SFIT", "Mumbai", ("St Francis Institute of Technology", "SFIT Borivali")),
    ("3188", "Don Bosco Institute of Technology, Kurla, Mumbai", "DBIT", "Mumbai", ("Don Bosco Institute of Technology", "DBIT Kurla")),
    ("3139", "Atharva College of Engineering, Malad, Mumbai", "ACE", "Mumbai", ("Atharva College Malad", "Atharva Engineering")),
    ("3263", "Shah and Anchor Kutchhi Engineering College, Chembur, Mumbai", "SAKEC", "Mumbai", ("Shah Anchor Kutchhi", "SAKEC Chembur")),
    ("3253", "SVKM's NMIMS Mukesh Patel School of Technology Management and Engineering, Vile Parle, Mumbai", "MPSTME", "Mumbai", ("NMIMS MPSTME", "MPSTME Vile Parle")),
    ("3227", "Rajiv Gandhi Institute of Technology, Andheri, Mumbai", "RGIT", "Mumbai", ("Rajiv Gandhi Institute of Technology", "RGIT Andheri")),
    ("3277", "Watumull Institute of Electronic Engineering and Computer Technology, Ulhasnagar", "WIEECT", "Ulhasnagar", ("Watumull Institute",)),
    ("3104", "SIES Graduate School of Technology, Nerul, Navi Mumbai", "SIES GST", "Navi Mumbai", ("SIES GST Nerul", "SIES Graduate School")),
    ("3176", "Pillai College of Engineering, New Panvel, Navi Mumbai", "PCE", "Navi Mumbai", ("Pillai College of Engineering", "PCE Panvel")),
    ("3414", "Saraswati Education Society's Saraswati College of Engineering, Kharghar, Navi Mumbai", "SCOE Kharghar", "Navi Mumbai", ("Saraswati College Kharghar",)),
    ("3458", "LTCE - Lokmanya Tilak College of Engineering, Koparkhairane, Navi Mumbai", "LTCE", "Navi Mumbai", ("Lokmanya Tilak College of Engineering", "LTCE Koparkhairane")),
    ("3477", "Terna Engineering College, Nerul, Navi Mumbai", "TEC", "Navi Mumbai", ("Terna Engineering College", "Terna Nerul")),
    ("3136", "Vasantdada Patil Pratishthan's College of Engineering, Sion, Mumbai", "VPPCOE", "Mumbai", ("Vasantdada Patil College Sion",)),
    ("3141", "M. H. Saboo Siddik College of Engineering, Byculla, Mumbai", "MHSSCE", "Mumbai", ("Saboo Siddik", "MHSSCE Byculla")),
    ("3172", "Xavier Institute of Engineering, Mahim, Mumbai", "XIE", "Mumbai", ("Xavier Institute of Engineering", "XIE Mahim")),
        ("3014", "SNDT Women's University - Usha Mittal Institute of Technology, Juhu, Mumbai", "U MIT", "Mumbai", ("Usha Mittal Institute of Technology", "SNDT Juhu")),
    ("3021", "K. J. Somaiya Polytechnic, Vidyavihar, Mumbai", "KJSP", "Mumbai", ("Somaiya Polytechnic",)),
        ("3193", "Smt. Indira Gandhi College of Engineering, Ghansoli, Navi Mumbai", "SIGCE", "Navi Mumbai", ("Indira Gandhi College Ghansoli",)),
    ("3279", "Rizvi College of Engineering, Bandra, Mumbai", "RCOE", "Mumbai", ("Rizvi College of Engineering", "Rizvi Bandra")),
    ("3383", "Thakur College of Engineering and Technology, Kandivali, Mumbai", "TCET", "Mumbai", ("Thakur College of Engineering", "TCET Kandivali")),
    ("3465", "Universal College of Engineering, Vasai, Palghar", "UCOE", "Palghar", ("Universal College Vasai",)),
    ("3466", "VIVA Institute of Technology, Virar, Palghar", "VIVA", "Palghar", ("VIVA Institute Virar",)),
    ("3469", "St. John College of Engineering and Management, Palghar", "SJCEM", "Palghar", ("St John College Palghar",)),
    ("3224", "Bharati Vidyapeeth College of Engineering, Belapur, Navi Mumbai", "BVCOE", "Navi Mumbai", ("Bharati Vidyapeeth Belapur", "BVCOE Navi Mumbai")),
        ("3251", "Pillai's HOC College of Engineering and Technology, Rasayani", "PHOCE", "Raigad", ("Pillai HOC", "HOC College Rasayani")),
    ("3145", "Vighnaharata Shikshan Sanstha's Vishwaniketan's Institute of Management Entrepreneurship and Engineering Technology, Khalapur", "VIMEET", "Raigad", ("Vishwaniketan iMEET",)),
    ("3154", "Bharat College of Engineering, Badlapur, Thane", "BCE", "Thane", ("Bharat College Badlapur",)),
    ("3254", "Datta Meghe College of Engineering, Airoli, Navi Mumbai", "DMCE", "Navi Mumbai", ("Datta Meghe College Airoli", "DMCE")),
        ("3281", "Anjuman-I-Islam's Kalsekar Technical Campus, Panvel, Navi Mumbai", "AIAKTC", "Navi Mumbai", ("Kalsekar Technical Campus", "AIKTC")),
    ("3252", "Konkan Gyanpeeth College of Engineering, Karjat, Raigad", "KGCE", "Raigad", ("Konkan Gyanpeeth", "KGCE Karjat")),
    ("3317", "Gharda Institute of Technology, Lavel, Ratnagiri", "GIT", "Ratnagiri", ("Gharda Institute of Technology",)),
    ("3480", "Finolex Academy of Management and Technology, Ratnagiri", "FAMT", "Ratnagiri", ("Finolex Academy",)),

    # --- Nagpur region -------------------------------------------------------
    ("4005", "Laxminarayan Institute of Technology, Nagpur", "LIT", "Nagpur", ("Laxminarayan Institute of Technology", "LIT Nagpur")),
    ("4025", "Government College of Engineering, Nagpur", "GCOEN", "Nagpur", ("Government College of Engineering Nagpur", "GCE Nagpur")),
    ("4115", "Shri Ramdeobaba College of Engineering and Management, Nagpur", "RCOEM", "Nagpur", ("Ramdeobaba", "Ramdeobaba College", "RCOEM Nagpur")),
    ("4116", "Ankush Shikshan Sanstha's G. H. Raisoni College of Engineering, Nagpur", "GHRCE", "Nagpur", ("GH Raisoni Nagpur", "GHRCE Nagpur", "Raisoni College Nagpur")),
    ("4149", "Yeshwantrao Chavan College of Engineering, Nagpur", "YCCE", "Nagpur", ("Yeshwantrao Chavan College of Engineering", "YCCE Wanadongri")),
    ("4123", "Lokmanya Tilak Jankalyan Shikshan Sanstha's Priyadarshini College of Engineering, Nagpur", "PCE Nagpur", "Nagpur", ("Priyadarshini College of Engineering",)),
    ("4133", "Sanmarg Shikshan Sanstha's Smt. Radhikatai Pandav College of Engineering, Nagpur", "SRPCE", "Nagpur", ("Radhikatai Pandav College",)),
    ("4134", "Guru Nanak Institute of Engineering and Technology, Kalmeshwar, Nagpur", "GNIET", "Nagpur", ("Guru Nanak Institute", "GNIET Kalmeshwar")),
    ("4135", "Shri Govindrao Wanjari College of Engineering and Technology, Nagpur", "GWCOET", "Nagpur", ("Govindrao Wanjari College",)),
    ("4148", "St. Vincent Pallotti College of Engineering and Technology, Nagpur", "SVPCET", "Nagpur", ("St Vincent Pallotti", "Pallotti College Nagpur")),
    ("4141", "Rajiv Gandhi College of Engineering and Research, Nagpur", "RGCER", "Nagpur", ("Rajiv Gandhi College of Engineering Nagpur",)),
    ("4173", "ITM Institute of Engineering and Technology, Nagpur", "ITM Nagpur", "Nagpur", ("ITM Nagpur",)),
    ("4104", "Kavi Kulguru Institute of Technology and Science, Ramtek", "KKITS", "Ramtek", ("Kavi Kulguru Institute", "KKITS Ramtek")),
    ("4004", "Government College of Engineering, Chandrapur", "GCOEC", "Chandrapur", ("Government College of Engineering Chandrapur", "GCE Chandrapur")),
    ("4151", "Ballarpur Institute of Technology, Ballarpur", "BIT", "Chandrapur", ("Ballarpur Institute of Technology",)),
    ("4152", "Ankush Shikshan Sanstha's G. H. Raisoni Academy of Engineering and Technology, Nagpur", "GHRAET", "Nagpur", ("Raisoni Academy Nagpur",)),
    ("4167", "Wainganga College of Engineering and Management, Nagpur", "WCEM", "Nagpur", ("Wainganga College",)),
    ("4174", "Nuva College of Engineering, Nagpur", "NCE Nagpur", "Nagpur", ("Nuva College Nagpur",)),
    ("4197", "Tulsiramji Gaikwad-Patil College of Engineering and Technology, Mohgaon, Nagpur", "TGPCET", "Nagpur", ("Tulsiramji Gaikwad Patil", "TGPCET")),

    # --- Nashik region ---------------------------------------------------------
    ("5121", "K. K. Wagh Institute of Engineering Education and Research, Nashik", "KKWIEER", "Nashik", ("KK Wagh", "KKWagh Nashik", "KK Wagh College")),
    ("5108", "Nashik District Maratha Vidya Prasarak Samaj's Karmaveer Adv. Baburao Ganpatrao Thakare College of Engineering, Nashik", "KBT COE", "Nashik", ("KBT College of Engineering", "Karmaveer Thakare College")),
    ("5109", "Sandip Foundation's Sandip Institute of Technology and Research Centre, Mahiravani, Nashik", "SITRC", "Nashik", ("Sandip Institute", "SITRC Nashik")),
    ("5124", "Jagadamba Education Society's S. N. D. College of Engineering and Research, Babulgaon, Nashik", "SNDCOE", "Nashik", ("SND College of Engineering", "SNDCOER")),
    ("5125", "Pravara Rural Education Society's Sir Visvesvaraya Institute of Technology, Chincholi, Nashik", "SVIT", "Nashik", ("Sir Visvesvaraya Institute", "SVIT Nashik")),
    ("5130", "Brahma Valley College of Engineering and Research, Trimbakeshwar, Nashik", "BVCER", "Nashik", ("Brahma Valley College",)),
    ("5151", "MET Bhujbal Knowledge City's MET Institute of Engineering, Adgaon, Nashik", "MET", "Nashik", ("MET Bhujbal", "MET Institute Nashik")),
    ("5173", "Shri Sureshdada Jain Institute of Technology, Chandwad, Nashik (SNJB)", "SNJB", "Nashik", ("SNJB Jain College of Engineering", "Jain Gurukul", "SSJIT")),
    ("5120", "Gokhale Education Society's Institute of Engineering and Technology, Nashik", "GES Nashik", "Nashik", ("Gokhale Education Society Nashik",)),
    ("5162", "Sandip University, Nashik", "Sandip University", "Nashik", ("Sandip University Nashik",)),
    ("5201", "Mahatma Gandhi Vidyamandir's Institute of Engineering, Nashik", "MGV Nashik", "Nashik", ("MGV Nashik",)),
    ("5012", "Government Polytechnic, Nashik", "GP Nashik", "Nashik", ("Government Polytechnic Nashik",)),

    # --- Chhatrapati Sambhajinagar (Aurangabad) region -------------------------
    ("2008", "Government College of Engineering, Chhatrapati Sambhajinagar (Aurangabad)", "GCOE AUR", "Sambhajinagar", ("GCE Aurangabad", "Government Engineering College Aurangabad", "GECA")),
    ("2020", "Shri Guru Gobind Singhji Institute of Engineering and Technology, Nanded", "SGGSIE&T", "Nanded", ("SGGS Nanded", "SGGS Institute", "SGGSIE&T Nanded")),
    ("2011", "Marathwada Institute of Technology, Chhatrapati Sambhajinagar (Aurangabad)", "MIT AUR", "Sambhajinagar", ("MIT Aurangabad", "Marathwada Institute of Technology")),
    ("2013", "MGM's Jawaharlal Nehru Engineering College, Chhatrapati Sambhajinagar", "JNEC", "Sambhajinagar", ("Jawaharlal Nehru Engineering College", "JNEC Aurangabad")),
    ("2021", "P. E. S. College of Engineering, Chhatrapati Sambhajinagar (Aurangabad)", "PESCOE", "Sambhajinagar", ("PES College of Engineering Aurangabad",)),
    ("2029", "Deogiri Institute of Engineering and Management Studies, Chhatrapati Sambhajinagar", "DIEMS", "Sambhajinagar", ("Deogiri Institute",)),
    ("2064", "Everest Educational Society's College of Engineering, Chhatrapati Sambhajinagar", "ECOE", "Sambhajinagar", ("Evergreen College Aurangabad",)),
    ("2250", "MGM's College of Engineering, Nanded", "MGM Nanded", "Nanded", ("MGM College of Engineering Nanded",)),
    ("2253", "Shreeyash Pratishthan's Shreeyash College of Engineering and Technology, Chhatrapati Sambhajinagar", "SYCET", "Sambhajinagar", ("Shreeyash College",)),
    ("2590", "Maharashtra Institute of Technology, Latur", "MIT Latur", "Latur", ("MIT Latur",)),
    ("2593", "M. S. Bidve Engineering College, Latur", "MSBEC", "Latur", ("MS Bidve", "Bidve Engineering College")),
    ("2531", "Vilasrao Deshmukh Foundation's School of Engineering, Latur", "VDF Latur", "Latur", ("VDF Engineering Latur",)),
    ("2035", "Chhatrapati Shahu College of Engineering, Chhatrapati Sambhajinagar", "CSCE", "Sambhajinagar", ("Chhatrapati Shahu College of Engineering",)),
    
    # --- Amravati region --------------------------------------------------------
    ("1002", "Government College of Engineering, Amravati", "GCOEA", "Amravati", ("Government Engineering College Amravati", "GCE Amravati")),
    ("1023", "Prof. Ram Meghe Institute of Technology and Research, Badnera, Amravati", "PRMITR", "Amravati", ("Prof Ram Meghe Institute", "PRMITR Badnera")),
    ("1107", "Sant Gadge Baba Amravati University's Department of Engineering and Technology, Amravati", "SGBAU", "Amravati", ("SGBAU Engineering", "Amravati University")),
    ("1076", "Sipna College of Engineering and Technology, Amravati", "SCET", "Amravati", ("Sipna College", "Sipna COET")),
    ("1079", "Shri Shivaji Education Society's College of Engineering and Technology, Akola", "SSESCOET", "Akola", ("Shivaji College of Engineering Akola",)),
    ("1080", "Government College of Engineering, Yavatmal", "GCOEY", "Yavatmal", ("Government Engineering Yavatmal",)),
    ("1117", "Dr. Rajendra Gode Institute of Technology and Research, Amravati", "DRGITR", "Amravati", ("Rajendra Gode Institute",)),
        ("1103", "HVPM's College of Engineering and Technology, Amravati", "HVPM", "Amravati", ("HVPM College", "HVPM Amravati")),
    ("1276", "Bapurao Deshmukh College of Engineering, Sevagram, Wardha", "BDCE", "Wardha", ("Bapurao Deshmukh College", "BDCE Sevagram")),
        ("1283", "Datta Meghe Institute of Higher Education and Research, Wardha", "DMIHER", "Wardha", ("Datta Meghe Wardha", "DMIMS")),
    ("1097", "P. R. Pote (Patil) Education and Welfare Trust's College of Engineering, Amravati", "PRPCOE", "Amravati", ("PR Pote College", "Patil College Amravati")),

    # --- Kolhapur / Sangli / Satara / Solapur ------------------------------------
    ("6214", "Rajarambapu Institute of Technology, Rajaramnagar, Islampur, Sangli", "RIT", "Sangli", ("Rajarambapu Institute of Technology", "RIT Islampur")),
    ("6222", "Dattajirao Kadam Technical Education Society's Textile and Engineering Institute, Ichalkaranji", "DKTE", "Ichalkaranji", ("DKTE Society's Textile Engineering", "Textile Engineering Institute Ichalkaranji")),
    ("6250", "D. Y. Patil College of Engineering and Technology, Kasaba Bawada, Kolhapur", "DYPK", "Kolhapur", ("DY Patil Kolhapur", "DYPCE Kolhapur")),
    ("6265", "Walchand Institute of Technology, Solapur", "WIT", "Solapur", ("Walchand Institute of Technology", "WIT Solapur")),
        ("6276", "New Satara College of Engineering and Management, Pandharpur, Solapur", "NSCEM", "Solapur", ("New Satara College Pandharpur",)),
    ("6184", "Sinhgad Institute of Technology, Lonavala, Pune", "SIT Lonavala", "Lonavala", ("Sinhgad Institute of Technology", "SIT Lonavala")),
    ("6255", "Kolhapur Institute of Technology's College of Engineering (Autonomous), Kolhapur", "KIT", "Kolhapur", ("Kolhapur Institute of Technology", "KIT College of Engineering")),
    ("6266", "Tatyasaheb Kore Institute of Engineering and Technology, Warananagar, Kolhapur", "TKIET", "Kolhapur", ("Tatyasaheb Kore Institute", "TKIET Warananagar")),
    ("6282", "Sanjay Ghodawat Institute, Atigre, Kolhapur", "SGI", "Kolhapur", ("Sanjay Ghodawat Institute", "SGI Atigre")),
    ("6288", "Sharad Institute of Technology, College of Engineering, Yadrav, Kolhapur", "SITCOE", "Kolhapur", ("Sharad Institute of Technology",)),
    ("6289", "Ashokrao Mane Group of Institutions, Vathar, Kolhapur", "AMGOI", "Kolhapur", ("Ashokrao Mane",)),
    ("6290", "Dattakala Group of Institutions, Swami Chincholi, Pune", "DGI", "Pune", ("Dattakala Group",)),
    ("6291", "Bhagwant Institute of Technology, Barshi, Solapur", "BIT Barshi", "Solapur", ("Bhagwant Institute Barshi",)),
    ("6292", "SVERI's College of Engineering, Pandharpur, Solapur", "SVERI", "Solapur", ("SVERI College of Engineering", "SVERI Pandharpur")),
    ("6295", "Dr. J. J. Magdum College of Engineering, Jaysingpur, Kolhapur", "JJMCOE", "Kolhapur", ("JJ Magdum College",)),
        ("6320", "D. Y. Patil Education Society's D. Y. Patil Technical Campus, Talsande, Kolhapur", "DYPTC", "Kolhapur", ("DY Patil Technical Campus Talsande",)),
    ("6321", "Annasaheb Dange College of Engineering and Technology, Ashta, Sangli", "ADCE", "Sangli", ("Annasaheb Dange College", "ADCE Ashta")),
    ("6331", "Padmabhooshan Vasantdada Patil Institute of Technology, Budhgaon, Sangli", "PVPIT", "Sangli", ("Vasantdada Patil Institute of Technology", "PVPIT Budhgaon")),
    ("6332", "Shree Santkrupa Institute of Engineering and Technology, Ghogaon, Karad", "SSIET", "Karad", ("Santkrupa Institute",)),
    # --- Karad city cluster (engineering / pharmacy / medical) ---------------
    ("6303", "Dr. Ashok Gujar Technical Institute's Dr. Daulatrao Aher College of Engineering, Karad", "DTAKCE", "Karad", ("Daulatrao Aher College of Engineering", "DACOE Karad", "DTAKCE Karad", "Dr. Daulatrao Aher College")),
    ("6008", "Government College of Pharmacy, Karad", "GCP Karad", "Karad", ("Govt College of Pharmacy Karad", "GCPK")),
    ("6516", "Krishna Charitable Trust's Krishna College of Pharmacy, Malkapur, Karad", "KCP Karad", "Karad", ("Krishna College of Pharmacy", "KCP Malkapur")),
    ("", "Krishna Institute of Medical Sciences (KIMS), Karad - Krishna Vishwa Vidyapeeth", "KIMS Karad", "Karad", ("Krishna Vishwa Vidyapeeth", "KVV Karad", "KIMSDU", "Krishna Institute of Medical Sciences Karad")),
    ("", "Sadguru Gadage Maharaj College, Karad", "SGM Karad", "Karad", ("SGMC Karad", "Sadguru Gadge Maharaj College", "SGM College Karad")),
    ("6337", "Late Narayandas Bhawandas Chhabada Institute of Engineering and Technology, Satara", "LNBCIET", "Satara", ("Chhabada Institute",)),
    ("6340", "Gourishankar Institute of Educational Foundation's College of Engineering, Limb, Satara", "GIE Satara", "Satara", ("Gourishankar Institute",)),
    ("6801", "Government College of Engineering, Jalgaon", "GCOEJ", "Jalgaon", ("Government Engineering Jalgaon", "GCE Jalgaon")),
    ("6802", "Shri Gulabrao Deokar College of Engineering, Jalgaon", "SGDCOE", "Jalgaon", ("Gulabrao Deokar College",)),
    ("6803", "North Maharashtra University's Institute of Technology, Jalgaon", "NMU Jalgaon", "Jalgaon", ("North Maharashtra University",)),
    ("6805", "R. C. Patel Institute of Technology, Shirpur, Dhule", "RCPIT", "Dhule", ("RC Patel Institute of Technology", "RCPIT Shirpur")),
    ("6806", "SSBT's College of Engineering and Technology, Bambhori, Jalgaon", "SSBT COET", "Jalgaon", ("SSBT College of Engineering", "Bambhori")),
    ("6807", "Shri Vile Parle Kelavani Mandal's Institute of Technology, Shirpur", "SVKM Shirpur", "Dhule", ("SVKM Institute Shirpur",)),
    ("6810", "Government College of Engineering, Ahmednagar", "GCOE Ahm", "Ahmednagar", ("Government Engineering College Ahmednagar", "GCE Ahmednagar")),
    ("6812", "Amrutvahini College of Engineering, Sangamner, Ahmednagar", "AVCOE", "Ahmednagar", ("Amrutvahini College", "AVCOE Sangamner")),
    ("6813", "Padmashri Dr. Vithalrao Vikhe Patil College of Engineering, Ahmednagar", "PDVVP COE", "Ahmednagar", ("Vithalrao Vikhe Patil College", "VVP College Ahmednagar")),
    ("6814", "Sanjivani College of Engineering, Kopargaon, Ahmednagar", "SCE Kopargaon", "Ahmednagar", ("Sanjivani College of Engineering", "Sanjivani Kopargaon")),
    ("6815", "Dr. Vithalrao Vikhe Patil Foundation's College of Engineering, Vilad Ghat, Ahmednagar", "VVP Vilad", "Ahmednagar", ("VVP Vilad Ghat",)),
    ("6817", "Shri Chhatrapati Shivajiraje College of Engineering, Dhangawadi, Pune", "SCSCE", "Pune", ("Shivajiraje College Dhangawadi",)),
        )


CET_COLLEGES: tuple[CetCollege, ...] = tuple(
    CetCollege(code=code, name=name, short_name=short, city=city, aliases=aliases)
    for code, name, short, city, aliases in _ENTRIES
)

# Canonical city list for the picker's filter pills (order = display order).
CET_CITIES: tuple[str, ...] = (
    "Pune",
    "Mumbai",
    "Navi Mumbai",
    "Thane",
    "Nagpur",
    "Nashik",
    "Sambhajinagar",
    "Kolhapur",
    "Sangli",
    "Satara",
    "Solapur",
    "Amravati",
    "Nanded",
    "Ahmednagar",
    "Jalgaon",
    "Latur",
    "Chandrapur",
    "Karad",
    "Wardha",
    "Dhule",
    "Raigad",
    "Ratnagiri",
    "Palghar",
)


def college_to_dict(college: CetCollege, custom: bool = False) -> dict:
    """Serializable dict for API responses (schema-agnostic on purpose)."""
    return {
        "code": college.code,
        "name": college.name,
        "short_name": college.short_name,
        "city": college.city,
        "aliases": list(college.aliases),
        "custom": custom,
    }


def get_college_by_code(code: str) -> CetCollege | None:
    code = (code or "").strip()
    if not code:
        return None  # code-less entries (KIMS, SGM) must not answer ""
    for college in CET_COLLEGES:
        if college.code == code:
            return college
    return None


def get_college_by_name(name: str) -> CetCollege | None:
    name = (name or "").strip().lower()
    if not name:
        return None
    for college in CET_COLLEGES:
        if college.name.lower() == name:
            return college
    for college in CET_COLLEGES:
        if college.short_name.lower() == name:
            return college
    return None


def _score(college: CetCollege, q: str) -> int:
    """Relevance score for a single query term (higher = better, 0 = no match)."""
    if not q:
        return 1
    short = college.short_name.lower()
    name = college.name.lower()
    code = college.code.lower()

    if code == q:
        return 100
    if short == q:
        return 95
    if code.startswith(q):
        return 90
    if short.startswith(q):
        return 85
    if any(a.lower().startswith(q) for a in college.aliases):
        return 80
    if q in name:
        # Prefer word-boundary hits ("pict" in "PICT, Pune" beats mid-word).
        return 70 if f" {q}" in f" {name}" or f"({q}" in name else 55
    if any(q in a.lower() for a in college.aliases):
        return 60
    if q in short:
        return 50
    return 0


def search_colleges(
    q: str = "",
    city: str = "",
    limit: int = 50,
) -> list[CetCollege]:
    """Ranked college search across name, short alias, aliases, code, city.

    `q` may contain multiple space-separated terms; every term must match
    (AND semantics) so "pune coep" and "6006" both behave sensibly. Results
    are sorted by total relevance, then by city, then name.
    """
    terms = [t for t in (q or "").lower().replace(",", " ").split() if t]
    city_norm = (city or "").strip().lower()

    scored: list[tuple[int, CetCollege]] = []
    for college in CET_COLLEGES:
        if city_norm and city_norm not in ("all", "all campuses"):
            if college.city.lower() != city_norm:
                continue
        total = 0
        matched_all = True
        for term in terms:
            s = _score(college, term)
            # Fall back to "any field contains term" so partial city names work
            # (e.g. "sambhaji" -> "Sambhajinagar").
            if s == 0 and term in college.search_blob():
                s = 40
            if s == 0:
                matched_all = False
                break
            total += s
        if matched_all:
            scored.append((total, college))

    scored.sort(key=lambda pair: (-pair[0], pair[1].city, pair[1].name))
    return [college for _, college in scored[: max(1, limit)]]
