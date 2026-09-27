#include "system_image.h"
#include "vfs_mount.h"
#include "apk_sha256.h"
#include "../android_java_app/apk_pins.h"
#include "../android_java_app/framework_pins.h"
#include "../android_java_app/ui_apk_pins.h"
#include <string.h>

/* The preinstalled APKs are on persistent C:, not copied to a RAM rootfs.
 * Only this fixed manifest may turn a guest name into a Symbian relative path.
 * The loader must still use RFs read-only and verify the bytes before use.
 */
typedef struct AppIndex {
    const char *package_name, *guest_path, *relative_on_c;
} AppIndex;
static const AppIndex kApps[] = {
    {"org.e63.dalvik.launcher", "/system/app/Launcher.apk",
      "system\\app\\Launcher.apk"},
    {"org.e63.dalvik.settings", "/system/app/Settings.apk",
      "system\\app\\Settings.apk"},
    {"org.e63.dalvik.store", "/system/app/Store.apk",
      "system\\app\\Store.apk"},
    {"org.e63.dalvik.systemui", "/system/app/SystemUI.apk",
      "system\\app\\SystemUI.apk"},
    {"org.e63.dalvik.packageinstaller", "/system/app/PackageInstaller.apk",
      "system\\app\\PackageInstaller.apk"},
    {"org.e63.dalvik.files", "/system/app/FileManager.apk",
      "system\\app\\FileManager.apk"}
};

const char *e63_system_app_path(const char *package_name)
    {
    size_t i;
    if (!package_name) return 0;
    for (i=0;i<sizeof(kApps)/sizeof(kApps[0]);++i)
        if (strcmp(kApps[i].package_name,package_name)==0)
            return kApps[i].guest_path;
    return 0;
    }

const char *e63_system_ui_app_path(const char *package_name)
    {
    size_t i;
    if (!package_name) return 0;
#if E63_UI_APK_PIN_COUNT > 0
    for (i=0;i<E63_UI_APK_PIN_COUNT;++i)
        if (strcmp(e63_ui_apk_pins[i].package_name,package_name)==0)
            return e63_ui_apk_pins[i].guest_path;
#else
    (void)i;
#endif
    return 0;
    }

E63SystemStatus e63_system_find(const char *guest_path, E63SystemFile *out)
    {
    E63MountRoute route;
    size_t i,j;
    if (!out || !guest_path) return E63_SYSTEM_INVALID;
    memset(out,0,sizeof(*out));
    if (e63_route_guest_path(guest_path,0,E63_CALLER_OS,&route)!=
        E63_ROUTE_OK || route.kind!=E63_MOUNT_BUNDLE_RO ||
        !route.read_only) return E63_SYSTEM_INVALID;
    for (i=0;i<sizeof(kApps)/sizeof(kApps[0]);++i)
        {
        if (strcmp(kApps[i].guest_path,guest_path)!=0) continue;
        for (j=0;j<E63_PIN_COUNT;++j)
            if (strcmp(kApps[i].package_name,e63_apk_pins[j].package_name)==0 &&
                strcmp(guest_path+strlen("/system/app/"),
                       e63_apk_pins[j].filename)==0)
                {
                out->guest_path=kApps[i].guest_path;
                out->relative_on_c=kApps[i].relative_on_c;
                out->package_name=kApps[i].package_name;
                out->bytes=e63_apk_pins[j].length;
                out->sha256=e63_apk_pins[j].sha256;
                out->kind=E63_SYSTEM_APP_APK;
                return E63_SYSTEM_OK;
                }
        return E63_SYSTEM_UNTRUSTED; /* manifest disagrees with APK pins */
        }
    /* Exact, independently pinned authentic-source UI candidates. They are
     * not dispatched via the old org.e63.dalvik.* Activity shim. */
#if E63_UI_APK_PIN_COUNT > 0
    for (i=0;i<E63_UI_APK_PIN_COUNT;++i)
        if (strcmp(e63_ui_apk_pins[i].guest_path,guest_path)==0)
            {
            out->guest_path=e63_ui_apk_pins[i].guest_path;
            out->relative_on_c=e63_ui_apk_pins[i].relative_on_c;
            out->package_name=e63_ui_apk_pins[i].package_name;
            out->bytes=e63_ui_apk_pins[i].apk_bytes;
            out->sha256=e63_ui_apk_pins[i].apk_sha256;
            out->kind=E63_SYSTEM_APP_APK;
            return E63_SYSTEM_OK;
            }
#endif
    /* This candidate manifest has genuine AOSP boot JAR/resource SHA pins,
     * not a claim that the files are installed or that Android can boot. */
#if E63_FRAMEWORK_PIN_COUNT > 0
    for (i=0;i<E63_FRAMEWORK_PIN_COUNT;++i)
        if (strcmp(e63_framework_pins[i].guest_path,guest_path)==0)
            {
            out->guest_path=e63_framework_pins[i].guest_path;
            out->relative_on_c=e63_framework_pins[i].relative_on_c;
            out->package_name=0;
            out->bytes=e63_framework_pins[i].length;
            out->sha256=e63_framework_pins[i].sha256;
            out->kind=(E63SystemFileKind)e63_framework_pins[i].kind;
            return E63_SYSTEM_OK;
            }
#endif
    return E63_SYSTEM_NOT_PRESENT;
    }

E63SystemStatus e63_system_verify(const E63SystemFile *file,
                                  const uint8_t *bytes, size_t length)
    {
    uint8_t digest[32];
    E63SystemFile expected;
    E63SystemStatus status;
    if (!file || !file->guest_path || !bytes) return E63_SYSTEM_INVALID;
    status=e63_system_find(file->guest_path,&expected);
    if (status!=E63_SYSTEM_OK) return status;
    if (file->kind!=expected.kind ||
        file->bytes!=expected.bytes ||
        !file->relative_on_c ||
        strcmp(file->relative_on_c,expected.relative_on_c)!=0 ||
        !file->sha256 ||
        memcmp(file->sha256,expected.sha256,32u)!=0 ||
        length!=expected.bytes) return E63_SYSTEM_UNTRUSTED;
    e63_apk_sha256(bytes,length,digest);
    return memcmp(digest,expected.sha256,32u)==0 ?
           E63_SYSTEM_OK : E63_SYSTEM_UNTRUSTED;
    }

const char *e63_system_status(E63SystemStatus status)
    {
    switch (status)
        {
        case E63_SYSTEM_OK: return "pinned read-only system file";
        case E63_SYSTEM_INVALID: return "invalid guest system path";
        case E63_SYSTEM_NOT_PRESENT: return "system file absent; no substitute";
        case E63_SYSTEM_UNTRUSTED: return "system file failed SHA-256 pin";
        case E63_SYSTEM_READ_ONLY: return "guest system is read-only";
        default: return "unknown system image status";
        }
    }
