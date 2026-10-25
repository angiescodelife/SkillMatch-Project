from django.contrib import admin

from .models import (
    CV, Application, CareerPreference, Employer, ExtractedSkill, LearningResource, MatchResult,
    Opportunity, OpportunitySkill, SavedOpportunity, Skill, SkillAlias, UserProfile, UserSkill,
)


class UserSkillInline(admin.TabularInline):
    model = UserSkill
    extra = 0
    autocomplete_fields = ['skill']


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'user_type', 'university', 'course_of_study', 'updated_at']
    list_filter = ['user_type', 'degree_level']
    search_fields = ['user__username', 'user__email', 'user__first_name', 'user__last_name']
    inlines = [UserSkillInline]


class SkillAliasInline(admin.TabularInline):
    model = SkillAlias
    extra = 1
    fields = ['alias']


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ['name', 'skill_type', 'category', 'in_dictionary']
    list_filter = ['skill_type', 'in_dictionary', 'category']
    search_fields = ['name', 'aliases__alias']
    readonly_fields = ['normalized_name']
    inlines = [SkillAliasInline]


class OpportunitySkillInline(admin.TabularInline):
    model = OpportunitySkill
    extra = 1
    autocomplete_fields = ['skill']


@admin.register(Opportunity)
class OpportunityAdmin(admin.ModelAdmin):
    list_display = ['title', 'employer', 'opportunity_type', 'work_style', 'location',
                    'is_active', 'is_sample', 'posted_at']
    list_filter = ['opportunity_type', 'work_style', 'is_active', 'is_sample']
    search_fields = ['title', 'employer__name']
    inlines = [OpportunitySkillInline]


@admin.register(Employer)
class EmployerAdmin(admin.ModelAdmin):
    list_display = ['name', 'location', 'is_sample', 'user']
    search_fields = ['name']


@admin.register(CV)
class CVAdmin(admin.ModelAdmin):
    list_display = ['original_name', 'profile', 'status', 'is_current', 'uploaded_at']
    list_filter = ['status', 'is_current']
    readonly_fields = ['extracted_text']


@admin.register(LearningResource)
class LearningResourceAdmin(admin.ModelAdmin):
    list_display = ['title', 'skill', 'provider', 'resource_type', 'hours', 'level']
    list_filter = ['resource_type', 'level']
    search_fields = ['title', 'skill__name']
    autocomplete_fields = ['skill']


@admin.register(MatchResult)
class MatchResultAdmin(admin.ModelAdmin):
    list_display = ['profile', 'opportunity', 'score', 'required_coverage', 'technical_score',
                    'soft_score', 'preference_score', 'computed_at']
    list_filter = ['opportunity__opportunity_type']
    readonly_fields = [f.name for f in MatchResult._meta.fields]


admin.site.register(CareerPreference)
admin.site.register(ExtractedSkill)
admin.site.register(SavedOpportunity)
admin.site.register(Application)
